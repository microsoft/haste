#!/bin/bash
###--mount type=bind,source=$AZ_BATCH_NODE_ROOT_DIR/haste/jobs,target=$AZ_BATCH_TASK_WORKING_DIR/data
### "mkdir -p $AZ_BATCH_NODE_ROOT_DIR/haste/jobs/$AZ_BATCH_JOB_ID/$AZ_BATCH_TASK_ID && echo 'This is a test file to check write permissions.' > $AZ_BATCH_NODE_ROOT_DIR/haste/jobs/$AZ_BATCH_JOB_ID/$AZ_BATCH_TASK_ID/test_write_permissions.txt && output=$(cat $AZ_BATCH_NODE_ROOT_DIR/haste/jobs/$AZ_BATCH_JOB_ID/$AZ_BATCH_TASK_ID/test_write_permissions.txt) && echo \"This is the output: $output\""
### Install necessary packages
apt update
apt install -y jq parted
disk_to_format="$(lsblk --json | jq -r '.blockdevices[] | select(.children == null and .fstype == null) | .name' | grep 'sd')"
echo "Disk to format: $disk_to_format"
mount_dir=$AZ_BATCH_NODE_ROOT_DIR/haste
mkdir -p $mount_dir
mkdir -p $AZ_BATCH_NODE_ROOT_DIR/haste/jobs

if [ -z "$disk_to_format" ]; then
    echo "Mounting existing partitions..."
    mount -a
 
else
    echo "Formatting disk $disk_to_format..."
    parted --script /dev/$disk_to_format mklabel gpt mkpart primary ext4 0% 100%
    # Wait until format disk is done ###
    sleep 5
    
    mkfs.ext4 /dev/${disk_to_format}1
    partprobe /dev/${disk_to_format}1
    lsblk -o NAME,HCTL,SIZE,MOUNTPOINT | grep -i "sd"
    echo "Mounting $disk_to_format1 to $mount_dir"
    mount /dev/${disk_to_format}1 $mount_dir
    echo "UUID=$(blkid -o value -s UUID /dev/${disk_to_format}1) $mount_dir   ext4   defaults,nofail   1   2" | tee -a /etc/fstab
fi

echo "Mounting completed. Current mounted filesystems:"
df -h

echo "Contents of /etc/fstab:"
cat /etc/fstab

# Create a test file on the mounted directory
test_file="$mount_dir/test_file.txt"
echo "This is a test file to verify the mounted directory." > $test_file
echo "Test file created at: $test_file"
echo "Contents of the test file:"
cat $test_file