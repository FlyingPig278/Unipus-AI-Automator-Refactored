#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="Unipus-AI-Automator"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-}"

if [[ -z "$VERSION" && -f "$ROOT_DIR/VERSION" ]]; then
  VERSION="$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")"
fi

if [[ -z "$VERSION" ]]; then
  echo "[ERROR] Version number not provided and VERSION file is missing." >&2
  exit 1
fi

cd "$ROOT_DIR"

if [[ ! -f run.bat ]]; then
  echo "[ERROR] run.bat not found." >&2
  exit 1
fi

if [[ ! -f run-portable.bat ]]; then
  echo "[ERROR] run-portable.bat not found." >&2
  exit 1
fi

if [[ ! -d python-embed ]]; then
  echo "[ERROR] python-embed directory not found." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "[ERROR] Working tree has uncommitted or untracked changes." >&2
  echo "        Commit or stash your changes before packaging." >&2
  exit 1
fi

CURRENT_TAG="v$VERSION"
PREVIOUS_TAG=""
while IFS= read -r tag; do
  if [[ "$tag" != "$CURRENT_TAG" ]]; then
    PREVIOUS_TAG="$tag"
    break
  fi
done < <(git tag --sort=-v:refname)

if [[ -z "$PREVIOUS_TAG" ]]; then
  PREVIOUS_TAG="initial"
fi

BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/unipus-release-XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT

echo "=========================================================="
echo "          Starting package $PROJECT_NAME v$VERSION"
echo "=========================================================="
echo "[INFO] Previous Git tag: $PREVIOUS_TAG"
echo "[INFO] Build directory: $BUILD_DIR"

make_source_tree() {
  local target_dir="$1"
  mkdir -p "$target_dir"
  git archive HEAD --format=tar | tar -xf - -C "$target_dir"
}

zip_dir() {
  local source_dir="$1"
  local zip_path="$2"
  rm -f "$zip_path"
  (cd "$source_dir" && zip -qr "$zip_path" .)
}

copy_changed_file() {
  local source_file="$1"
  local target_root="$2"
  local target_path="$target_root/$source_file"
  mkdir -p "$(dirname "$target_path")"
  cp -a "$source_file" "$target_path"
}

echo
echo "[1/3] --- Creating Lite version ---"
LITE_DIR="$BUILD_DIR/lite"
LITE_ZIP="$ROOT_DIR/$PROJECT_NAME-Lite-v$VERSION.zip"
make_source_tree "$LITE_DIR"
cp run.bat "$LITE_DIR/run.bat"
rm -f "$LITE_DIR/run-portable.bat"
zip_dir "$LITE_DIR" "$LITE_ZIP"
echo "     - Lite version created: $(basename "$LITE_ZIP")"

echo
echo "[2/3] --- Creating Portable version ---"
PORTABLE_DIR="$BUILD_DIR/portable"
PORTABLE_ZIP="$ROOT_DIR/$PROJECT_NAME-Portable-v$VERSION.zip"
make_source_tree "$PORTABLE_DIR"
cp -a python-embed "$PORTABLE_DIR/python-embed"
cp run-portable.bat "$PORTABLE_DIR/run.bat"
rm -f "$PORTABLE_DIR/run-portable.bat"
zip_dir "$PORTABLE_DIR" "$PORTABLE_ZIP"
echo "     - Portable version created: $(basename "$PORTABLE_ZIP")"

echo
echo "[3/3] --- Creating Update version ---"
if [[ "$PREVIOUS_TAG" == "initial" ]]; then
  echo "     - This is the first version, skipping update package creation."
else
  UPDATE_DIR="$BUILD_DIR/update"
  UPDATE_ZIP="$ROOT_DIR/$PROJECT_NAME-update_${PREVIOUS_TAG}_to_v$VERSION.zip"
  mkdir -p "$UPDATE_DIR"

  mapfile -t changed_files < <(git diff --name-only --diff-filter=dACM "$PREVIOUS_TAG"..HEAD)
  for file in "${changed_files[@]}"; do
    if [[ "$file" == "run.bat" || "$file" == "run-portable.bat" ]]; then
      echo "       Skipping edition-specific launcher: $file"
      continue
    fi
    copy_changed_file "$file" "$UPDATE_DIR"
  done

  mapfile -t deleted_files < <(git diff --name-only --diff-filter=D "$PREVIOUS_TAG"..HEAD)
  if git cat-file -e "$PREVIOUS_TAG:run-portable.bat" 2>/dev/null; then
    deleted_files+=("run-portable.bat")
  fi
  if (( ${#deleted_files[@]} > 0 )); then
    printf '%s\n' "${deleted_files[@]}" > "$UPDATE_DIR/files_to_delete.txt"
  fi

  if (( ${#changed_files[@]} == 0 && ${#deleted_files[@]} == 0 )); then
    echo "     - No files changed, skipping update package creation."
  else
    {
      echo "Unipus AI Automator - Update Instructions"
      echo "========================================="
      echo
      echo "Update from version: $PREVIOUS_TAG"
      echo "Update to version:   v$VERSION"
      echo
      echo "HOW TO UPDATE:"
      echo "----------------"
      echo "1. IMPORTANT: Back up your existing installation directory first."
      echo "2. If files_to_delete.txt exists in this package, delete all listed files and folders from your installation directory."
      echo "3. Copy all other files and folders from this package into your installation directory, overwriting existing files."
      echo "4. Launcher scripts are edition-specific and are not included in this generic update package; keep your existing run.bat."
    } > "$UPDATE_DIR/UPDATE_README.txt"

    git log "$PREVIOUS_TAG"..HEAD --oneline --no-merges > "$UPDATE_DIR/CHANGELOG.txt"
    zip_dir "$UPDATE_DIR" "$UPDATE_ZIP"
    echo "     - Update version created: $(basename "$UPDATE_ZIP")"
  fi
fi

echo
echo "=========================================================="
echo "          All packaging tasks are completed!"
echo "=========================================================="
