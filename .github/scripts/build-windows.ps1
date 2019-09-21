
$ErrorActionPreference = "Stop"

function exec {
    [CmdletBinding()]
    param([Parameter(Position=0,Mandatory=1)][scriptblock]$cmd)
    Write-Host "$cmd"
    & $cmd
    if ($lastexitcode -ne 0) {
        throw ("ERROR exit code " -f $lastexitcode)
    }
}

& $env:CONDA\shell\condabin\conda-hook.ps1

exec { conda create --yes --name pyenv_build python=$env:PYTHON_VERSION numpy=$env:NUMPY_VERSION cython jpeg zlib }
exec { conda activate pyenv_build }

# Check that we have the expected version and architecture for Python
exec { python --version }
exec { python -c "import struct; print(struct.calcsize('P') * 8)" }
  
# output what's installed
exec { pip freeze }
    
# Build the compiled extension.
# -u disables output buffering which caused intermixing of lines
# when the external tools were started  
exec { cmd /E:ON /V:ON /C .\appveyor\run_with_env.cmd python -u setup.py bdist_wheel }