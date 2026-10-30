# Image Comparer: previews two images to temp; the frontend shows them with a hover slider and Send / Save results buttons.

import nodes


class ImageComparer(nodes.PreviewImage):
    @classmethod
    def INPUT_TYPES(s):
        return {
            "optional": {
                "image_a": ("IMAGE", {"tooltip": "Shown left of the slider. Send and Save results use this image."}),
                "image_b": ("IMAGE", {"tooltip": "Shown right of the slider. Without it, the first two images of image_a are compared."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    FUNCTION = "compare"
    CATEGORY = "Smart Image Tools"
    DESCRIPTION = "Compares two images with a hover slider. Send loads image A into a Load Image node; Save results copies it to the output folder."

    def compare(self, image_a=None, image_b=None, prompt=None, extra_pnginfo=None):
        ui = {"a_images": [], "b_images": []}
        if image_a is not None:
            ui["a_images"] = self.save_images(image_a, "smart.compare", prompt, extra_pnginfo)["ui"]["images"]
        if image_b is not None:
            ui["b_images"] = self.save_images(image_b, "smart.compare", prompt, extra_pnginfo)["ui"]["images"]
        return {"ui": ui}
