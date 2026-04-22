envfile=$1
condaEnvName="haste_env"
if conda info --envs | grep -q "^${condaEnvName}\b";
then
  echo "Updating existing conda env: ${condaEnvName}" && conda env update -f ${envfile} --prune;
else
  echo "No existing conda env found, creating it using ${envfile}" && conda env create -f ${envfile};
fi
