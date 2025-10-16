param(
  [ValidateSet('minimal','normal','opengl')] [string]$Mode = 'minimal'
)

Set-Location $PSScriptRoot

# Paths
$BLENDER_DIR     = (Resolve-Path ".\blender").Path
$BLENDER_EXE     = Join-Path $BLENDER_DIR "blender.exe"
$BLENDER_PYTHON  = Join-Path $BLENDER_DIR "4.2\python\bin\python.exe"

# Ensure pip exists
& $BLENDER_PYTHON -m ensurepip
& $BLENDER_PYTHON -m pip install --upgrade pip setuptools wheel

# Mode flags
switch ($Mode) {
  'minimal' {
    $env:INFINIGEN_MINIMAL_INSTALL = "True"
    Remove-Item Env:INFINIGEN_INSTALL_CUSTOMGT -ErrorAction SilentlyContinue
  }
  'normal' {
    Remove-Item Env:INFINIGEN_MINIMAL_INSTALL, Env:INFINIGEN_INSTALL_CUSTOMGT -ErrorAction SilentlyContinue
  }
  'opengl' {
    Remove-Item Env:INFINIGEN_MINIMAL_INSTALL -ErrorAction SilentlyContinue
    $env:INFINIGEN_INSTALL_CUSTOMGT = "True"
  }
}

# Install into Blender's site-packages
& $BLENDER_PYTHON -m pip install -e .

# Verify
& $BLENDER_EXE -b --python-expr "import infinigen, bpy; print('OK:', bpy.app.version_string)"
