#!/bin/bash

# Copyright (C) 2024 Michael Piazza
#
# This file is part of Smart Notes.
#
# Smart Notes is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Smart Notes is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Smart Notes.  If not, see <https://www.gnu.org/licenses/>.


find_python_env() {
    # List of common virtual environment directory names
    local env_dirs=(".env" ".venv" "env" "venv")

    # Function to check if a directory contains a Python executable
    is_python_env() {
        [[ -d "$1" && -f "$1/bin/python" ]]
    }

    # Check each directory
    for dir in "${env_dirs[@]}"; do
        if is_python_env "$dir"; then
            echo "$dir"
            return 0
        fi
    done

    echo ""
    return 1
}

get_python_version() {
    local venv_path="$1"
    local python_path="$venv_path/bin/python"

    if [[ ! -f "$python_path" ]]; then
        echo "Error: Python executable not found in $venv_path" >&2
        return 1
    fi

    local version=$("$python_path" -c "import sys; print(f'python{sys.version_info.major}.{sys.version_info.minor}')")
    echo "$version"
}


build () {
  echo "Building..."
  rm -rf dist
  mkdir -p dist/vendor

  cp *.py dist/
  cp manifest.json dist/
  cp config.json dist/
  cp -r src dist/
  cp LICENSE dist/
  cp changelog.md dist/
  echo "environment = \"PROD\"" > dist/env.py

  # Nuke any pycache
  rm -rf dist/__pycache__

  local python_env=$(find_python_env)
  local python_version=$(get_python_version "$python_env")

  cp $python_env dist

  # Copy deps
  cp -r "$python_env/lib/$python_version/site-packages/aiohttp" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/aiosignal" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/async_timeout" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/frozenlist" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/attrs" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/multidict" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/yarl" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/idna" dist/vendor/
  ## Sentry
  cp -r "$python_env/lib/$python_version/site-packages/sentry_sdk" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/certifi" dist/vendor/
  cp -r "$python_env/lib/$python_version/site-packages/urllib3" dist/vendor/
  # Dotenv
  cp -r "$python_env/lib/$python_version/site-packages/dotenv" dist/vendor/


  # Zip it
  cd dist
  zip -r smart-notes.ankiaddon *
  cd ..
}

DEV_ADDON_DIR="$ANKI_ADDONS_DIR/smart-notes"

clean () {
  echo "Cleaning..."
  rm -rf dist
  unlink "$DEV_ADDON_DIR"
}

link-dev () {
  ln -s $(pwd) "$DEV_ADDON_DIR"
}

# Tests a production build by symlinking dist folder
link-dist () {
  ln -s $(pwd)/dist "$DEV_ADDON_DIR"
}

anki () {
   /Applications/Anki.app/Contents/MacOS/anki
}

test-dev () {
  clean
  link-dev
  anki
}

test-build () {
  clean
  build
  link-dist
  anki
}

if [ "$1" == "build" ]; then
  build
elif [ "$1" == "clean" ]; then
  clean
elif [ "$1" == "link-dev" ]; then
  link-dev
elif [ "$1" == "link-dist" ]; then
  link-dist
elif [ "$1" == "test-dev" ]; then
  test-dev
elif [ "$1" == "test-build" ]; then
  test-build
else
  echo "Invalid argument: $1"
fi

echo "Done"
