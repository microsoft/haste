# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import torch

print("========================================")
print(f"Is CUDA available? {torch.cuda.is_available()}")
print(f"Number of GPUs available: {torch.cuda.device_count()}")
print(f"Torch built with CUDA: {torch.backends.cuda.is_built()}")
print(f"cuDNN Version: {torch.backends.cudnn.version()}")
print(f"cuDNN Enabled: {torch.backends.cudnn.enabled}")
print(f"cuDNN available: {torch.backends.cudnn.is_available()}")
print("========================================")
