# Common helpers for Smart Image Tools

import torch
import torch.nn.functional as F

def _to_bhwc(x):
    # Ensure [B, H, W, C]
    if x.ndim == 3:
        if x.shape[0] in (1, 3): return x.movedim(0, -1).unsqueeze(0)
        if x.shape[-1] in (1, 3): return x.unsqueeze(0)
    return x

def _mask_to_bhw(m):
    if m.ndim == 2: return m.unsqueeze(0)
    if m.ndim == 3 and m.shape[-1] == 1: return m.squeeze(-1)
    if m.ndim == 4 and m.shape[-1] == 1: return m.squeeze(-1).squeeze(1)
    return m

def _mask_has_pixels(mask_2d, thresh=0.0):
    return bool(torch.any(mask_2d > thresh).item())

def _bbox_from_mask(mask_2d, thresh=0.0):
    idx = (mask_2d > thresh).nonzero(as_tuple=False)
    if idx.numel() == 0: return None
    ys = idx[:, 0]; xs = idx[:, 1]
    y0 = int(torch.min(ys)); y1 = int(torch.max(ys)) + 1
    x0 = int(torch.min(xs)); x1 = int(torch.max(xs)) + 1
    return [x0, y0, max(1, x1 - x0), max(1, y1 - y0)]

def _resize_img(img_bhwc, tw, th, mode="bicubic"):
    # mode="bicubic" is generally better for upscaling (Zoom In)
    # mode="area" is better for downscaling (Zoom Out/Stitch) to prevent aliasing
    t = img_bhwc.movedim(-1, 1) # to BCHW
    
    # align_corners=False is standard for bicubic/bilinear; not used for area/nearest
    align = False if mode not in ["nearest", "area"] else None
    
    t = F.interpolate(t, size=(th, tw), mode=mode, align_corners=align)
    return t.movedim(1, -1)

def _resize_mask(mask_bhw, tw, th):
    t = mask_bhw.unsqueeze(1)
    t = F.interpolate(t, size=(th, tw), mode="nearest")
    return t.squeeze(1)

def _edge_pad(image_bhwc, x, y, w, h):
    B, H, W, C = image_bhwc.shape
    pad_l = max(0, -x)
    pad_t = max(0, -y)
    pad_r = max(0, (x + w) - W)
    pad_b = max(0, (y + h) - H)
    
    read_x = max(0, x)
    read_y = max(0, y)
    read_w = w - pad_l - pad_r
    read_h = h - pad_t - pad_b
    
    if read_w <= 0 or read_h <= 0:
        # Return empty canvas if crop is completely outside
        return torch.zeros((B, h, w, C), device=image_bhwc.device, dtype=image_bhwc.dtype), (pad_l, pad_t)
    
    crop = image_bhwc[:, read_y:read_y+read_h, read_x:read_x+read_w, :]
    canvas = torch.zeros((B, h, w, C), device=image_bhwc.device, dtype=image_bhwc.dtype)
    canvas[:, pad_t:pad_t+read_h, pad_l:pad_l+read_w, :] = crop
    
    if pad_t > 0: canvas[:, :pad_t, :, :] = canvas[:, pad_t:pad_t+1, :, :]
    if pad_b > 0: canvas[:, -pad_b:, :, :] = canvas[:, -pad_b-1:-pad_b, :, :]
    if pad_l > 0: canvas[:, :, :pad_l, :] = canvas[:, :, pad_l:pad_l+1, :]
    if pad_r > 0: canvas[:, :, -pad_r:, :] = canvas[:, :, -pad_r-1:-pad_r, :]
    
    return canvas, (pad_l, pad_t)

def _gaussian_kernel1d(sigma, kernel_size):
    x = torch.arange(kernel_size, dtype=torch.float32) - (kernel_size - 1) / 2
    kernel = torch.exp(-0.5 * (x / sigma)**2)
    return kernel / kernel.sum()

def _gaussian_blur(mask_bhw, blur_px=16):
    if blur_px <= 0: return mask_bhw
    _, h, w = mask_bhw.shape
    if h <= 1 or w <= 1:
        return mask_bhw

    sigma = float(blur_px) * 0.33
    k_size = 2 * int(3.0 * sigma + 0.5) + 1
    if k_size % 2 == 0: k_size += 1
    max_kernel = max(3, 2 * min(h, w) - 1)
    k_size = min(k_size, max_kernel)
    if k_size % 2 == 0: k_size -= 1
    sigma = max(0.1, min(sigma, k_size / 6.0))
    
    kernel = _gaussian_kernel1d(sigma, k_size).to(mask_bhw.device, dtype=mask_bhw.dtype)
    kernel_x = kernel.view(1, 1, 1, k_size)
    kernel_y = kernel.view(1, 1, k_size, 1)
    
    x = mask_bhw.unsqueeze(1) 
    pad = k_size // 2
    pad_mode = 'reflect' if pad < h and pad < w else 'replicate'
    
    x = F.pad(x, (pad, pad, 0, 0), mode=pad_mode)
    x = F.conv2d(x, kernel_x)
    x = F.pad(x, (0, 0, pad, pad), mode=pad_mode)
    x = F.conv2d(x, kernel_y)
    
    return torch.clamp(x.squeeze(1), 0.0, 1.0)

def _color_match_moments(image_bhwc, reference_bhwc, amount=0.0, mask_bhw=None):
    amount = float(max(0.0, min(1.0, amount)))
    if amount <= 0.0:
        return image_bhwc

    img = image_bhwc.float()
    ref = reference_bhwc.float()
    eps = 1e-5

    if mask_bhw is not None:
        weights = torch.clamp(mask_bhw.float(), 0.0, 1.0).unsqueeze(-1)
        if float(weights.sum().item()) <= eps:
            weights = None
    else:
        weights = None

    if weights is None:
        img_mean = img.mean(dim=(1, 2), keepdim=True)
        ref_mean = ref.mean(dim=(1, 2), keepdim=True)
        img_std = img.std(dim=(1, 2), keepdim=True).clamp_min(eps)
        ref_std = ref.std(dim=(1, 2), keepdim=True).clamp_min(eps)
    else:
        denom = weights.sum(dim=(1, 2), keepdim=True).clamp_min(eps)
        img_mean = (img * weights).sum(dim=(1, 2), keepdim=True) / denom
        ref_mean = (ref * weights).sum(dim=(1, 2), keepdim=True) / denom
        img_var = (((img - img_mean) ** 2) * weights).sum(dim=(1, 2), keepdim=True) / denom
        ref_var = (((ref - ref_mean) ** 2) * weights).sum(dim=(1, 2), keepdim=True) / denom
        img_std = torch.sqrt(img_var).clamp_min(eps)
        ref_std = torch.sqrt(ref_var).clamp_min(eps)

    matched = (img - img_mean) * (ref_std / img_std) + ref_mean
    corrected = torch.lerp(img, matched, amount)
    return torch.clamp(corrected, 0.0, 1.0).to(image_bhwc.dtype)
