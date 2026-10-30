# Smart Image Stitcher (Still Image Optimized)

import torch
from .common_image import (
    _to_bhwc, _resize_img, _gaussian_blur, _mask_to_bhw, _resize_mask,
    _edge_pad, _color_match_moments
)


def _box_feather(h, w, feather_pixels, device):
    mask = torch.ones((1, h, w), dtype=torch.float32, device=device)
    # Zero band of the full blur radius so the blurred edge actually reaches zero.
    margin = feather_pixels
    mask[:, :margin, :] = 0
    mask[:, -margin:, :] = 0
    mask[:, :, :margin] = 0
    mask[:, :, -margin:] = 0
    return _gaussian_blur(mask, blur_px=feather_pixels)

class SmartImageStitcher:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "original_image": ("IMAGE",),
                "processed_image": ("IMAGE",),
                "stitcher_info": ("DICT",),
                "feather_pixels": ("INT", {"default": 32, "min": 0, "max": 256, "step": 1, "tooltip": "Feather width in original-image pixels. Only used when feather_mode is Pixels."}),
                "blend_mode": (["Box Feather", "Mask Feather", "Hard Paste"], {"default": "Box Feather", "tooltip": "Choose the stitch mask. Feather amount applies to both box and mask feather modes."}),
                "resize_full_image_output": (["Restore Original Size", "Keep Resized Image"], {"default": "Restore Original Size", "tooltip": "Only affects Crop node no-mask mode: Resize Full Image."}),
                "enable_color_match": ("BOOLEAN", {"default": False, "tooltip": "When enabled, shifts the processed crop toward the original region's color and contrast before stitching."}),
                "color_match_amount": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Matches the processed crop color statistics toward the original image before stitching. 0 disables it, 1 applies full correction."}),
                "feather_mode": (["Auto", "Pixels"], {"default": "Auto", "tooltip": "Auto scales the feather to the crop size (about 6% of its short side), so a 50px face gets a light soft edge and a large region gets a wide blend. Pixels uses feather_pixels."}),
            },
            "optional": {
                "mask": ("MASK",),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "stitch"
    CATEGORY = "Smart Image Tools"

    def stitch(self, original_image, processed_image, stitcher_info, feather_pixels, blend_mode="Box Feather", resize_full_image_output="Restore Original Size", enable_color_match=False, color_match_amount=0.35, feather_mode="Auto", mask=None):
        
        base = _to_bhwc(original_image).contiguous().clone() # Clone to avoid modifying original input in memory
        processed = _to_bhwc(processed_image).contiguous()
        # Some edit VAEs (Qwen Image 2.1) decode RGBA; paste only the channels the original has.
        if processed.shape[-1] > base.shape[-1]:
            processed = processed[..., :base.shape[-1]]

        if not stitcher_info or stitcher_info.get("bypass", False):
            return (base,)

        required_keys = ("x", "y", "w", "h", "padL", "padT")
        if any(key not in stitcher_info for key in required_keys):
            return (base,)

        if stitcher_info.get("full_image_resize", False) and resize_full_image_output == "Keep Resized Image":
            return (processed,)
        
        # Prepare optional mask if requested
        mask_input = None
        if blend_mode == "Mask Feather" and mask is not None:
            mask_input = _mask_to_bhw(mask).contiguous()
        
        B_base, H, W, C = base.shape
        B_proc = processed.shape[0]
        if B_proc == 0:
            return (base,)
        
        sx = stitcher_info["x"]
        sy = stitcher_info["y"]
        sw = stitcher_info["w"] 
        sh = stitcher_info["h"] 
        
        num_items = len(sx)
        if num_items == 0:
            return (base,)
        
        for b in range(B_base):
            if b >= num_items: break
            
            x, y, w, h = sx[b], sy[b], sw[b], sh[b]
            if w <= 0 or h <= 0:
                continue
            
            proc_idx = b % B_proc
            patch = processed[proc_idx:proc_idx+1]
            
            # 1. Resize processed patch back to Source Size (w, h)
            # The AI gave us a high-res image. We must shrink it back to the original slot.
            # "area" interpolation is best for downscaling.
            patch_resized = _resize_img(patch, w, h, mode="area")

            if feather_mode == "Auto":
                feather = max(2, round(min(w, h) * 0.06))
            else:
                # Cap the feather so small crops are not faded away entirely.
                feather = min(feather_pixels, min(w, h) // 4)

            # 2. Prepare blending mask.
            if blend_mode == "Mask Feather" and mask_input is not None:
                mask_idx = b % mask_input.shape[0]
                curr_mask = mask_input[mask_idx:mask_idx+1]

                # Resize mask to fit the destination slot (w, h)
                mask_resized = _resize_mask(curr_mask, w, h)

                # Masks usually touch the crop border, so also fade to zero at the box edge to avoid a hard seam.
                if feather > 0:
                    mask_resized = _gaussian_blur(mask_resized, blur_px=feather)
                    mask_resized = mask_resized * _box_feather(h, w, feather, base.device)

                mask_tensor = mask_resized.unsqueeze(-1)

            elif blend_mode == "Box Feather" and feather > 0:
                mask_tensor = _box_feather(h, w, feather, base.device).unsqueeze(-1)
            else:
                mask_tensor = torch.ones((1, h, w, 1), dtype=torch.float32, device=base.device)

            if enable_color_match and color_match_amount > 0:
                reference_patch, _ = _edge_pad(base[b:b+1], x, y, w, h)
                patch_resized = _color_match_moments(
                    patch_resized,
                    reference_patch,
                    amount=color_match_amount,
                    mask_bhw=mask_tensor.squeeze(-1),
                )

            # 3. Paste into Base
            x0 = max(0, x)
            y0 = max(0, y)
            x1 = min(W, x + w)
            y1 = min(H, y + h)
            
            patch_x0 = max(0, -x)
            patch_y0 = max(0, -y)
            
            vis_w = x1 - x0
            vis_h = y1 - y0
            
            if vis_w <= 0 or vis_h <= 0:
                continue

            patch_slice = patch_resized[0, patch_y0 : patch_y0 + vis_h, patch_x0 : patch_x0 + vis_w, :]
            mask_slice = mask_tensor[0, patch_y0 : patch_y0 + vis_h, patch_x0 : patch_x0 + vis_w, :]
            
            base_slice = base[b, y0:y1, x0:x1, :]
            
            composed = patch_slice * mask_slice + base_slice * (1.0 - mask_slice)
            
            base[b, y0:y1, x0:x1, :] = composed

        return (base,)
