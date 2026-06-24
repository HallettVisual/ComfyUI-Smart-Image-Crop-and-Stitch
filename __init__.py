from .smart_image_crop import SmartImageCrop
from .smart_image_stitcher import SmartImageStitcher

NODE_CLASS_MAPPINGS = {
    "SmartImageCrop": SmartImageCrop,
    "SmartImageStitcher": SmartImageStitcher,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SmartImageCrop": "Smart Image Crop (Still)",
    "SmartImageStitcher": "Smart Image Stitcher (Still)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
