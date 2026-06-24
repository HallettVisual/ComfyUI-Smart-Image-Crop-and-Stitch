# Smart Image Crop (Still Image Optimized)

import torch
import torch.nn.functional as F
import math
import numpy as np
try:
    import cv2
except ImportError:
    cv2 = None
from .common_image import (
    _to_bhwc, _mask_to_bhw, _bbox_from_mask, _edge_pad, 
    _resize_img, _resize_mask, _mask_has_pixels
)


def _snap_up(value, divisible_by):
    return max(divisible_by, int(math.ceil(float(value) / divisible_by) * divisible_by))


def _snap_down(value, divisible_by):
    return max(divisible_by, int(math.floor(float(value) / divisible_by) * divisible_by))

class SmartImageCrop:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "mask": ("MASK",),
            
            # Resolution Handling
            "resolution_mode": (["Automatic", "Manual"], {"default": "Automatic"}),
            
            # Simplified Resolution Controls
            "max_resolution": ("INT", {"default": 2048, "min": 256, "max": 16384, "step": 64, "tooltip": "MAX LIMIT: If the cropped area is larger than this, it will be SCALED DOWN so its longest side equals this value."}),
            "min_resolution": ("INT", {"default": 768, "min": 64, "max": 2048, "step": 64, "tooltip": "MIN LIMIT: If the cropped area is smaller than this, it will be SCALED UP so its longest side equals this value."}),
            
            # Manual Mode controls
            "manual_width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 8}),
            "manual_height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 8}),
            
            # Mask shaping
            "mask_grow_pixels": ("INT", {"default": 32, "min": -1024, "max": 1024, "step": 8, "tooltip": "Grow or shrink the detected mask before cropping. Positive grows, negative shrinks."}),
            
            "patch_mask_holes": ("BOOLEAN", {"default": True, "tooltip": "Fills small holes and gaps in the detected mask to ensure a solid shape."}),
            "no_mask_mode": (["Bypass", "Resize Full Image", "Crop Full Image"], {"default": "Bypass", "tooltip": "What to do when no mask pixels are detected."}),
            
            "force_divisibility": ([8, 16, 32, 64, 112, 128, 256], {"default": 128, "tooltip": "Ensure output dimensions are divisible by this number (crucial for VAEs)"}),
        }}

    RETURN_TYPES = ("IMAGE", "MASK", "DICT", "IMAGE")
    RETURN_NAMES = ("crop_image", "crop_mask", "stitcher_info", "preview_overlay")
    FUNCTION = "run"
    CATEGORY = "Smart Image Tools"

    def _morph_close(self, mask_bhw, kernel_size=9):
        # Helper to close holes: Dilate then Erode
        if kernel_size < 1: return mask_bhw
        pad = kernel_size // 2
        m = mask_bhw.unsqueeze(1)
        # Dilate (Max Pool)
        m = F.max_pool2d(m, kernel_size=kernel_size, stride=1, padding=pad)
        # Erode (-Max Pool of negated)
        m = -F.max_pool2d(-m, kernel_size=kernel_size, stride=1, padding=pad)
        return m.squeeze(1)

    def _grow_or_shrink_mask(self, mask_bhw, pixels):
        if pixels == 0:
            return mask_bhw

        kernel_size = abs(int(pixels)) * 2 + 1
        if kernel_size < 3:
            return mask_bhw

        pad = kernel_size // 2
        m = mask_bhw.unsqueeze(1)
        if pixels > 0:
            m = F.max_pool2d(m, kernel_size=kernel_size, stride=1, padding=pad)
        else:
            m = -F.max_pool2d(-m, kernel_size=kernel_size, stride=1, padding=pad)
        return (m.squeeze(1) > 0).float()

    def _prepare_mask(self, mask, patch_mask_holes, mask_grow_pixels):
        raw = _mask_to_bhw(mask).contiguous().float()
        if cv2 is None or (not patch_mask_holes and mask_grow_pixels == 0):
            msk = (raw > 0).float()
            if patch_mask_holes:
                msk = self._morph_close(msk, kernel_size=9)
                msk = self._fill_enclosed_holes(msk)
            return self._grow_or_shrink_mask(msk, mask_grow_pixels)

        device = raw.device
        dtype = raw.dtype
        masks_np = (raw.detach().cpu().numpy() > 0).astype(np.uint8)
        processed = []

        close_kernel = np.ones((9, 9), dtype=np.uint8)
        grow_pixels = int(mask_grow_pixels)
        grow_kernel = None
        if grow_pixels != 0:
            grow_size = abs(grow_pixels) * 2 + 1
            grow_kernel = np.ones((grow_size, grow_size), dtype=np.uint8)

        for curr in masks_np:
            if patch_mask_holes:
                curr = cv2.morphologyEx(curr, cv2.MORPH_CLOSE, close_kernel)
                padded = np.pad(curr * 255, ((1, 1), (1, 1)), mode="constant", constant_values=0)
                cv2.floodFill(padded, None, (0, 0), 255)
                holes = (padded[1:-1, 1:-1] == 0).astype(np.uint8)
                curr = np.maximum(curr, holes)

            if grow_kernel is not None:
                if grow_pixels > 0:
                    curr = cv2.dilate(curr, grow_kernel, iterations=1)
                else:
                    curr = cv2.erode(curr, grow_kernel, iterations=1)

            processed.append(curr)

        processed_np = np.stack(processed, axis=0).astype(np.float32)
        return torch.from_numpy(processed_np).to(device=device, dtype=dtype)

    def _fill_enclosed_holes(self, mask_bhw):
        if cv2 is None:
            return mask_bhw

        device = mask_bhw.device
        dtype = mask_bhw.dtype
        solid = (mask_bhw > 0).float()
        masks_np = solid.detach().cpu().numpy().astype(np.uint8)
        filled = []

        for curr in masks_np:
            mask_u8 = curr * 255
            padded = np.pad(mask_u8, ((1, 1), (1, 1)), mode="constant", constant_values=0)
            cv2.floodFill(padded, None, (0, 0), 255)
            holes = (padded[1:-1, 1:-1] == 0).astype(np.uint8) * 255
            filled.append(np.maximum(mask_u8, holes))

        filled_np = np.stack(filled, axis=0).astype(np.float32) / 255.0
        return torch.from_numpy(filled_np).to(device=device, dtype=dtype)

    def _target_size_from_max(self, w, h, max_resolution, divisible_by):
        if w >= h:
            tw = _snap_down(max_resolution, divisible_by)
            th = _snap_up(tw * h / w, divisible_by)
        else:
            th = _snap_down(max_resolution, divisible_by)
            tw = _snap_up(th * w / h, divisible_by)
        return max(divisible_by, tw), max(divisible_by, th)

    def run(self, image, mask, resolution_mode, max_resolution, min_resolution, manual_width, manual_height, mask_grow_pixels, patch_mask_holes, no_mask_mode, force_divisibility):
        
        # 1. Prepare Inputs
        img = _to_bhwc(image).contiguous()
        msk = self._prepare_mask(mask, patch_mask_holes, mask_grow_pixels)

        B, H, W, C = img.shape

        valid_mask_items = [
            _mask_has_pixels(msk[b % msk.shape[0]])
            for b in range(B)
        ]

        if not any(valid_mask_items):
            passthrough_mask = torch.cat(
                [msk[b % msk.shape[0]:b % msk.shape[0] + 1] for b in range(B)],
                dim=0
            )

            if no_mask_mode == "Resize Full Image":
                tw, th = self._target_size_from_max(W, H, max_resolution, force_divisibility)
                resized = _resize_img(img, tw, th, mode="bicubic")
                resized_mask = torch.ones((B, th, tw), device=img.device, dtype=msk.dtype)
                stitcher_info = {
                    "bypass": False,
                    "x": [0 for _ in range(B)],
                    "y": [0 for _ in range(B)],
                    "w": [W for _ in range(B)],
                    "h": [H for _ in range(B)],
                    "padL": [0 for _ in range(B)],
                    "padT": [0 for _ in range(B)],
                    "target_w": [tw for _ in range(B)],
                    "target_h": [th for _ in range(B)],
                    "original_size": (W, H),
                    "full_image_resize": True,
                }
                return (resized, resized_mask, stitcher_info, img.clone())

            if no_mask_mode == "Crop Full Image":
                full_mask = torch.ones((B, H, W), device=img.device, dtype=msk.dtype)
                stitcher_info = {
                    "bypass": False,
                    "x": [0 for _ in range(B)],
                    "y": [0 for _ in range(B)],
                    "w": [W for _ in range(B)],
                    "h": [H for _ in range(B)],
                    "padL": [0 for _ in range(B)],
                    "padT": [0 for _ in range(B)],
                    "target_w": [W for _ in range(B)],
                    "target_h": [H for _ in range(B)],
                    "original_size": (W, H),
                    "full_image_resize": False,
                }
                return (img, full_mask, stitcher_info, img.clone())

            stitcher_info = {
                "bypass": True,
                "x": [],
                "y": [],
                "w": [],
                "h": [],
                "padL": [],
                "padT": [],
                "target_w": [],
                "target_h": [],
                "original_size": (W, H),
                "full_image_resize": False,
            }
            return (img, passthrough_mask, stitcher_info, img.clone())
        
        crops = []
        crop_masks = []
        
        # Stitcher data lists
        stitch_x = []
        stitch_y = []
        stitch_w = []
        stitch_h = []
        stitch_padL = []
        stitch_padT = []
        stitch_target_w = []
        stitch_target_h = []
        
        # Overlay for previewing
        overlay = img.clone()
        debug_color = torch.tensor([0.0, 1.0, 0.0], device=img.device) # Green box

        for b in range(B):
            mask_idx = b % msk.shape[0]

            # A. Detect Bounding Box
            bbox = _bbox_from_mask(msk[mask_idx])

            if bbox is None:
                crop = img[b:b+1]
                crop_mask = msk[mask_idx:mask_idx+1]
                crops.append(crop)
                crop_masks.append(crop_mask)
                stitch_x.append(0)
                stitch_y.append(0)
                stitch_w.append(W)
                stitch_h.append(H)
                stitch_padL.append(0)
                stitch_padT.append(0)
                stitch_target_w.append(W)
                stitch_target_h.append(H)
                continue
            
            x, y, w, h = bbox
            
            # B. Use the grown/shrunk mask bounds as the crop context.
            cx = x + w / 2
            cy = y + h / 2
            
            new_w = w
            new_h = h
            
            # C. Determine Crop Region & Target Resolution
            if resolution_mode == "Automatic":
                aspect = new_w / new_h
                snapped_min = _snap_up(min_resolution, force_divisibility)
                snapped_max = _snap_down(max_resolution, force_divisibility)
                snapped_max = max(snapped_min, snapped_max)
                limit_ar = snapped_max / snapped_min
                
                if aspect > limit_ar:
                    tw = snapped_max
                    th = snapped_min
                    
                elif aspect < (1.0 / limit_ar):
                    tw = snapped_min
                    th = snapped_max
                    
                else:
                    curr_min = min(new_w, new_h)
                    curr_max = max(new_w, new_h)
                    
                    scale = 1.0
                    
                    if curr_min < snapped_min:
                        scale = snapped_min / curr_min
                    elif curr_max > snapped_max:
                        scale = snapped_max / curr_max
                        
                    target_w = new_w * scale
                    target_h = new_h * scale

                    if curr_min < snapped_min:
                        tw = _snap_up(target_w, force_divisibility)
                        th = _snap_up(target_h, force_divisibility)
                    elif curr_max > snapped_max:
                        tw = _snap_down(target_w, force_divisibility)
                        th = _snap_down(target_h, force_divisibility)
                    else:
                        tw = int(round(target_w / force_divisibility) * force_divisibility)
                        th = int(round(target_h / force_divisibility) * force_divisibility)
                        tw = max(force_divisibility, tw)
                        th = max(force_divisibility, th)
                
            else:
                tw = _snap_up(manual_width, force_divisibility)
                th = _snap_up(manual_height, force_divisibility)

            # Square up capture aspect ratio to match target aspect ratio
            # This ensures the crop we take from the original image perfectly matches the 
            # shape of the tensor we are sending to the AI, preventing squashing.
            target_ar = tw / th
            current_ar = new_w / new_h
            
            if current_ar > target_ar:
                # Need more height in source crop to match target shape
                req_h = new_w / target_ar
                new_h = req_h
            else:
                # Need more width in source crop to match target shape
                req_w = new_h * target_ar
                new_w = req_w
                
            # D. Crop from Source
            # Coordinates in original image space
            crop_x = int(cx - new_w / 2)
            crop_y = int(cy - new_h / 2)
            crop_w = int(new_w)
            crop_h = int(new_h)
            
            canvas, (padL, padT) = _edge_pad(img[b:b+1], crop_x, crop_y, crop_w, crop_h)
            
            # E. Resize to Target (Upscale/Downscale)
            # Use 'bicubic' for cleaner upscaling (Zoom In)
            patch_resized = _resize_img(canvas, tw, th, mode="bicubic")
            
            # Mask handling
            mask_canvas, _ = _edge_pad(msk[mask_idx:mask_idx+1].unsqueeze(-1), crop_x, crop_y, crop_w, crop_h)
            mask_patch = mask_canvas[:, :, :, 0]
            mask_resized = _resize_mask(mask_patch, tw, th)
            
            crops.append(patch_resized)
            crop_masks.append(mask_resized)
            
            # Save original dimensions for Stitcher
            stitch_x.append(crop_x)
            stitch_y.append(crop_y)
            stitch_w.append(crop_w) 
            stitch_h.append(crop_h) 
            stitch_padL.append(padL)
            stitch_padT.append(padT)
            stitch_target_w.append(tw)
            stitch_target_h.append(th)
            
            # Draw preview: red mask tint plus green crop border.
            mask_preview = msk[mask_idx, y:y+h, x:x+w].unsqueeze(-1)
            red = torch.tensor([1.0, 0.0, 0.0], device=img.device, dtype=img.dtype)
            overlay[b, y:y+h, x:x+w, :] = torch.lerp(overlay[b, y:y+h, x:x+w, :], red, mask_preview * 0.35)

            dx = max(0, crop_x); dy = max(0, crop_y)
            dw = min(W - dx, crop_w); dh = min(H - dy, crop_h)
            if dw > 0 and dh > 0:
                overlay[b, dy:dy+2, dx:dx+dw, :] = debug_color
                overlay[b, dy+dh-2:dy+dh, dx:dx+dw, :] = debug_color
                overlay[b, dy:dy+dh, dx:dx+2, :] = debug_color
                overlay[b, dy:dy+dh, dx+dw-2:dx+dw, :] = debug_color

        final_crop_image = torch.cat(crops, dim=0)
        final_crop_mask = torch.cat(crop_masks, dim=0)
        
        stitcher_info = {
            "bypass": False,
            "x": stitch_x,
            "y": stitch_y,
            "w": stitch_w, 
            "h": stitch_h,
            "padL": stitch_padL,
            "padT": stitch_padT,
            "target_w": stitch_target_w,
            "target_h": stitch_target_h,
            "original_size": (W, H),
            "full_image_resize": False,
        }

        return (final_crop_image, final_crop_mask, stitcher_info, overlay)
