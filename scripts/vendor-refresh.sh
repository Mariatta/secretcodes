#!/usr/bin/env bash
# Copy upstream browser-side dependencies from node_modules into
# secretcodes/static/vendor/. Run after `npm ci`.
#
# Called by the vendor-refresh GitHub Action when Dependabot bumps a
# version in package.json. Safe to run locally too.

set -euo pipefail

V=secretcodes/static/vendor
mkdir -p "$V/bootstrap" "$V/sortablejs" "$V/tagify"

cp node_modules/bootstrap/dist/css/bootstrap.min.css         "$V/bootstrap/"
cp node_modules/bootstrap/dist/css/bootstrap.min.css.map     "$V/bootstrap/"
cp node_modules/bootstrap/dist/js/bootstrap.bundle.min.js    "$V/bootstrap/"
cp node_modules/bootstrap/dist/js/bootstrap.bundle.min.js.map "$V/bootstrap/"
cp node_modules/bootstrap/LICENSE                            "$V/bootstrap/"

cp node_modules/sortablejs/Sortable.min.js  "$V/sortablejs/"
cp node_modules/sortablejs/LICENSE          "$V/sortablejs/"

cp node_modules/@yaireo/tagify/dist/tagify.js   "$V/tagify/"
cp node_modules/@yaireo/tagify/dist/tagify.css  "$V/tagify/"
cp node_modules/@yaireo/tagify/LICENSE          "$V/tagify/"
# We don't ship Tagify's 1.2 MB sourcemap, so drop the dangling
# sourceMappingURL reference — otherwise WhiteNoise's manifest storage
# fails `collectstatic` looking for the missing tagify.js.map.
grep -v sourceMappingURL "$V/tagify/tagify.js" > "$V/tagify/tagify.js.tmp"
mv "$V/tagify/tagify.js.tmp" "$V/tagify/tagify.js"
