# Changelog

## 2.1.1

- FLUX.2 Klein 4B workflow: `max_resolution` is now 1536, for faster edits on large masks and lower-VRAM cards.

## 2.1.0

- Added `max_megapixels` to Smart Image Crop to limit the crop sent to the model on lower-VRAM cards. Off by default, so existing workflows behave the same.
- Mask Paint: fixed the painter being squeezed by a second image preview with Nodes 2.0.
- Mask Paint: fixed two painters sharing a mask file when one was copied from the other, which let the Reference mask replace the Plate mask. New masks are saved per node.
- Mask Paint: undo uses a quarter of the memory on large images.
- Smart Image Crop: `preview_overlay` is limited to 2048 px on the long side, saving memory and preview time on very large images.

## 2.0.0

- Added automatic empty-mask pass-through behavior for crop and stitch nodes.
- Removed the old fallback center crop when no mask is detected.
- Added `color_match_amount` to Smart Image Stitcher.
- Hardened feather blur for very small crop regions.
- Added smoke tests for bypass, color match, and tiny-crop blending.
- Fixed `Mask Feather` pasting a hard rectangle when the mask touches the crop border; the blend now also fades to zero at the crop edge.
- `Box Feather` now fades fully to zero at the crop edge.
- Stitch feather is capped to a quarter of the crop's short side so small crops are not faded away.
- Added `context_padding` (default 16) to Smart Image Crop to include surrounding scene around the mask.
- `mask_grow_pixels` now defaults to 0.
- Added `feather_mode` to Smart Image Stitcher. `Auto` (default) scales the feather to about 6% of the crop's short side; `Pixels` uses `feather_pixels`.
- Added `Send to Load Image` node and a right-click "Send to Load Image" item on nodes showing images.
- Added `Load Image (Mask Paint)`: Load Image with an inline brush/erase mask painter. `Send to Load Image` can be wired to it via `to_loader` -> `receive`.
- `Send to Load Image` now saves to the output folder like Save Image (`filename_prefix`), replacing a separate Save Image node.
- Mask Paint: Brush, Erase, Rect (drag) and Stamp (256–2048 squares with a size preview box) are exclusive tools; image size readout; brush up to 1024 px, resized with Alt+drag (left or right button) or [ ].
- Mask Paint: the painter now fills the node (removed the conflicting built-in image preview widget) and accepts file drops anywhere on it.
- Smart Image Stitcher accepts RGBA results (Qwen Image 2.1 decodes 4 channels) and pastes only the original's channels.
- Added `Image Comparer (Smart)`: hover-slider A/B comparison with `Send` (into a Load Image node) and `Save results` (to the output folder) buttons.
- Replaced the example workflow with `workflows/Smart Crop & Stitch - FLUX.2 Klein 4B.json`, plus its example image and mask in `workflows/input/`.
- Mask Paint: the image now loads after a drag-drop of a large file; before, it could stay broken with the previous image's size and mask.
- Mask Paint and Image Comparer: the mouse wheel now zooms the canvas over these nodes, like any other node.
