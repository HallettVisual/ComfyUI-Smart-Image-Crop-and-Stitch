# ComfyUI Smart Image Crop and Stitch

Smart Image Crop and Stitch is a small ComfyUI custom node pack for mask-driven inpaint and edit workflows. It crops only the masked region with configurable context, sends that crop through your processing chain, then stitches the result back into the original image.

The goal is simple: spend resolution where the edit is happening, keep the surrounding image intact, and avoid manual crop math.

## Nodes

### Smart Image Crop

Finds the active mask bounds, adds padding, optionally fills small mask gaps, and outputs a resized crop for downstream processing.

Outputs:

- `crop_image`: the cropped image region
- `crop_mask`: the matching mask
- `stitcher_info`: placement metadata for the stitcher
- `preview_overlay`: the original image with a crop boundary preview

If the mask is empty, the node automatically becomes a pass-through. It returns the original image and marks `stitcher_info` as bypassed.

### Smart Image Stitcher

Resizes the processed crop back to its original location and blends it into the source image.

Features:

- feathered edge blending
- optional mask-based blending
- automatic pass-through when the crop node found no mask
- color matching against the original image region

## Color Matching

The stitcher includes `color_match_amount`, a value from `0.0` to `1.0`.

- `0.0`: disabled
- `0.35`: default, gentle correction
- `1.0`: full RGB mean/std matching to the original region

This is useful when the edited crop comes back with a different exposure, contrast, or color cast than the original image.

## Installation

Clone this repository into your ComfyUI custom nodes folder:

```powershell
cd ComfyUI/custom_nodes
git clone https://github.com/HallettVisual/ComfyUI-Smart-Image-Crop-and-Stitch.git
```

Restart ComfyUI. The nodes appear under:

```text
Smart Image Tools
```

## Basic Workflow

1. Connect your source `IMAGE` and `MASK` to `Smart Image Crop`.
2. Send `crop_image` and `crop_mask` into your inpaint, edit, upscale, or detailer workflow.
3. Connect the processed crop to `Smart Image Stitcher`.
4. Connect the original image and `stitcher_info` from the crop node.
5. Adjust feathering and color matching until the edit blends naturally.

## Recommended Settings

- `padding_pixels`: start with `32` to `96`
- `min_resolution`: use `768` or `1024` for small masked details
- `max_resolution`: use `1536` or `2048` for larger edits
- `force_divisibility`: `64` or `128` works well for most VAE/model pipelines
- `color_match_amount`: start at `0.25` to `0.45`

## Empty Mask Behavior

When no mask pixels are detected, both nodes are bypassed automatically:

- no center crop is created
- the original image passes through unchanged
- the stitcher ignores the processed input and returns the original image

This makes the nodes safe to leave in workflows where mask generation is optional.

## Development

Run the smoke tests from the repository folder:

```powershell
python .\tests\test_smoke.py
```

The tests cover empty-mask bypass, tiny-crop feathering, and the color-match stitch path.

## License

MIT License. See [LICENSE](LICENSE).
