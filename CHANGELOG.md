# Changelog

## Unreleased

- Added automatic empty-mask pass-through behavior for crop and stitch nodes.
- Removed the old fallback center crop when no mask is detected.
- Added `color_match_amount` to Smart Image Stitcher.
- Hardened feather blur for very small crop regions.
- Added smoke tests for bypass, color match, and tiny-crop blending.
