# Load Image with an inline mask painter. The frontend paints the mask and uploads it to input/smart_masks.

import hashlib
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
import folder_paths
import node_helpers
import nodes


def _mask_path(mask_file):
    return folder_paths.get_annotated_filepath(f"{mask_file} [input]")


class LoadImageMaskPaint(nodes.LoadImage):
    @classmethod
    def INPUT_TYPES(s):
        types = super().INPUT_TYPES()
        return {"required": {
            **types["required"],
            "mask_file": ("STRING", {"default": "", "tooltip": "Painted mask saved by the inline painter. Set automatically."}),
        },
        # Frontend-only socket for the Send to Load Image wire; stripped from the prompt before queueing.
        "optional": {
            "receive": ("SMART_SEND", {"tooltip": "Connect Send to Load Image's to_loader here to send results into this loader."}),
        }}

    CATEGORY = "Smart Image Tools"
    DESCRIPTION = "Load Image with a mask painter built into the node. The painter starts from the image's alpha mask; once painted, the painted mask is used."

    def load_image(self, image, mask_file):
        img, mask = super().load_image(image)
        if not mask_file:
            return (img, mask)

        painted = node_helpers.pillow(Image.open, _mask_path(mask_file)).convert("L")
        painted = torch.from_numpy(np.array(painted).astype(np.float32) / 255.0)[None].to(device=mask.device, dtype=mask.dtype)
        # The painter starts from the image's alpha mask, so the painted mask replaces it.
        h, w = img.shape[1], img.shape[2]
        if painted.shape[1:] != (h, w):
            painted = F.interpolate(painted[None], size=(h, w), mode="bilinear")[0]
        return (img, painted.expand(img.shape[0], -1, -1).clone())

    @classmethod
    def IS_CHANGED(s, image, mask_file):
        m = hashlib.sha256(super().IS_CHANGED(image).encode())
        if mask_file:
            with open(_mask_path(mask_file), "rb") as f:
                m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(s, image, mask_file):
        if mask_file and not folder_paths.exists_annotated_filepath(f"{mask_file} [input]"):
            return "Invalid mask file: {}".format(mask_file)
        return super().VALIDATE_INPUTS(image)
