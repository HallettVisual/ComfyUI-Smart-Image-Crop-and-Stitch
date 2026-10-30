from .smart_image_crop import SmartImageCrop
from .smart_image_stitcher import SmartImageStitcher
from .send_to_load_image import SendToLoadImage
from .load_image_mask_paint import LoadImageMaskPaint
from .image_comparer import ImageComparer

NODE_CLASS_MAPPINGS = {
    "SmartImageCrop": SmartImageCrop,
    "SmartImageStitcher": SmartImageStitcher,
    "SmartSendToLoadImage": SendToLoadImage,
    "SmartLoadImageMaskPaint": LoadImageMaskPaint,
    "SmartImageComparer": ImageComparer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SmartImageCrop": "Smart Image Crop (Still)",
    "SmartImageStitcher": "Smart Image Stitcher (Still)",
    "SmartSendToLoadImage": "Send to Load Image",
    "SmartLoadImageMaskPaint": "Load Image (Mask Paint)",
    "SmartImageComparer": "Image Comparer (Smart)",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
