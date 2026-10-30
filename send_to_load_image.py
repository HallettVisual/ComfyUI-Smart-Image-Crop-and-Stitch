# Send to Load Image: saves like Save Image, then the frontend points a chosen loader node at the saved file.

import nodes


class SendToLoadImage(nodes.SaveImage):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "target_node_id": ("INT", {"default": 0, "min": 0, "max": 0xffffffff, "tooltip": "Load Image node to receive the image when to_loader is not wired. Use the 'Target' button on this node to pick one."}),
                "auto_send": ("BOOLEAN", {"default": True, "tooltip": "Send to the target every run. When off, use the 'Send now' button."}),
                "filename_prefix": ("STRING", {"default": "ComfyUI", "tooltip": "Saved to the output folder like Save Image. Supports the same %date% style formatting."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    # Wire to_loader into a Load Image (Mask Paint) receive input to pick the target. The frontend strips this link before queueing.
    RETURN_TYPES = ("SMART_SEND",)
    RETURN_NAMES = ("to_loader",)
    FUNCTION = "send"
    CATEGORY = "Smart Image Tools"
    DESCRIPTION = "Saves images to the output folder like Save Image, and loads the first one into the chosen Load Image node."

    def send(self, image, target_node_id, auto_send, filename_prefix="ComfyUI", prompt=None, extra_pnginfo=None):
        return {**self.save_images(image, filename_prefix, prompt, extra_pnginfo), "result": (None,)}
