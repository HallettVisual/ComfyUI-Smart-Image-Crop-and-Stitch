import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

// Moves output images into LoadImage nodes: the "Send to Load Image" node, plus a right-click item on any node showing images.

function outputImages(node) {
    return app.nodeOutputs?.[node.id]?.images ?? node.images ?? [];
}

const LOADER_TYPES = ["LoadImage", "SmartLoadImageMaskPaint"];

export function loadImageNodes() {
    return app.graph.nodes.filter((n) => LOADER_TYPES.includes(n.type) && n.mode !== 4);
}

function wiredTarget(node) {
    const linkId = node.outputs?.[0]?.links?.[0];
    if (linkId == null) return null;
    const link = app.graph.links.get?.(linkId) ?? app.graph.links[linkId];
    return link ? app.graph.getNodeById(link.target_id) : null;
}

export function nodeLabel(n) {
    return `${n.title || "Load Image"} #${n.id}`;
}

export function sendTo(target, img) {
    const widget = target.widgets?.find((w) => w.name === "image");
    if (!widget) return;
    const name = img.subfolder ? `${img.subfolder}/${img.filename}` : img.filename;
    const value = `${name} [${img.type || "output"}]`;
    const values = widget.options?.values;
    if (Array.isArray(values) && !values.includes(value)) values.push(value);
    widget.value = value;
    widget.callback?.(value);
    app.graph.setDirtyCanvas(true, true);
}

function resolveTarget(node) {
    const wired = wiredTarget(node);
    if (wired) return wired;
    const id = node.widgets.find((w) => w.name === "target_node_id").value;
    const targets = loadImageNodes();
    return targets.find((n) => String(n.id) === String(id)) ?? (targets.length === 1 ? targets[0] : null);
}

function sendFromNode(node) {
    const img = outputImages(node)[0];
    const target = resolveTarget(node);
    if (img && target) sendTo(target, img);
}

app.registerExtension({
    name: "SmartImageTools.SendToLoadImage",

    setup() {
        // The to_loader -> receive wire only picks the target; drop it so the server never sees the loop.
        const graphToPrompt = app.graphToPrompt;
        app.graphToPrompt = async function () {
            const res = await graphToPrompt.apply(this, arguments);
            for (const n of Object.values(res.output)) {
                if (n.class_type === "SmartLoadImageMaskPaint") delete n.inputs.receive;
            }
            return res;
        };

        api.addEventListener("executed", ({ detail }) => {
            const node = app.graph.getNodeById(Number(detail?.node));
            if (node?.type !== "SmartSendToLoadImage") return;
            if (!node.widgets.find((w) => w.name === "auto_send").value) return;
            const img = detail.output?.images?.[0];
            const target = resolveTarget(node);
            if (img && target) sendTo(target, img);
        });
    },

    nodeCreated(node) {
        if (node.comfyClass !== "SmartSendToLoadImage") return;
        const idWidget = node.widgets.find((w) => w.name === "target_node_id");
        // Clicking cycles through the Load Image nodes in the graph.
        const targetButton = node.addWidget("button", "target", null, () => {
            const targets = loadImageNodes();
            if (!targets.length || wiredTarget(node)) return;
            const i = targets.findIndex((n) => String(n.id) === String(idWidget.value));
            idWidget.value = Number(targets[(i + 1) % targets.length].id);
            app.graph.setDirtyCanvas(true, false);
        }, { serialize: false });
        targetButton.serialize = false;
        Object.defineProperty(targetButton, "label", {
            get() {
                const target = resolveTarget(node);
                if (!target) return "Target: click to pick Load Image";
                return wiredTarget(node) ? `Target (wired): ${nodeLabel(target)}` : `Target: ${nodeLabel(target)}`;
            },
            set() {},
        });
        const sendButton = node.addWidget("button", "Send now", null, () => sendFromNode(node), { serialize: false });
        sendButton.serialize = false;
    },

    getNodeMenuItems(node) {
        const images = outputImages(node);
        if (!images.length) return [];
        const img = images[node.imageIndex ?? 0] ?? images[0];
        const targets = loadImageNodes();
        if (!targets.length) return [];
        if (targets.length === 1) {
            return [null, { content: "Send to Load Image", callback: () => sendTo(targets[0], img) }];
        }
        return [null, {
            content: "Send to Load Image",
            has_submenu: true,
            submenu: {
                options: targets.map((t) => ({ content: nodeLabel(t), callback: () => sendTo(t, img) })),
            },
        }];
    },
});
