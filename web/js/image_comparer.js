import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { loadImageNodes, nodeLabel, sendTo } from "./send_to_load_image.js";

// Image Comparer (Smart): hover slider between image A and B, with Send, Save results and Save as buttons for image A.

function viewUrl(img) {
    const params = new URLSearchParams({ filename: img.filename, subfolder: img.subfolder ?? "", type: img.type ?? "temp" });
    return api.apiURL(`/view?${params}`);
}

// Copies a previewed temp image into the input or output folder. Re-uploading the same image under the same name is deduplicated by the server.
async function copyImage(img, name, type, subfolder) {
    const blob = await (await fetch(viewUrl(img))).blob();
    const body = new FormData();
    body.append("image", blob, name);
    body.append("subfolder", subfolder);
    body.append("type", type);
    const resp = await api.fetchApi("/upload/image", { method: "POST", body });
    if (resp.status !== 200) throw new Error(`Upload failed (${resp.status})`);
    const data = await resp.json();
    return { filename: data.name, subfolder: data.subfolder, type: data.type };
}

function timestamp() {
    const d = new Date();
    const p = (v) => String(v).padStart(2, "0");
    return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

// The last Save as folder is a browser directory handle kept in IndexedDB, so the server never sees a path.
function folderStore(mode, fn) {
    return new Promise((resolve, reject) => {
        const open = indexedDB.open("SmartImageComparer", 1);
        open.onupgradeneeded = () => open.result.createObjectStore("folders");
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
            const req = fn(open.result.transaction("folders", mode).objectStore("folders"));
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        };
    });
}

async function pickFolder() {
    const last = await folderStore("readonly", (s) => s.get("last")).catch(() => undefined);
    const dir = await window.showDirectoryPicker({ id: "smart-image-comparer", mode: "readwrite", ...(last && { startIn: last }) });
    await folderStore("readwrite", (s) => s.put(dir, "last")).catch(() => {});
    return dir;
}

// Picks name, name_002, name_003... so an existing file is never overwritten.
async function freeName(dir, base, ext) {
    for (let n = 1; ; n++) {
        const name = n === 1 ? `${base}${ext}` : `${base}_${String(n).padStart(3, "0")}${ext}`;
        try {
            await dir.getFileHandle(name);
        } catch (err) {
            if (err.name === "NotFoundError") return name;
            throw err;
        }
    }
}

function el(tag, style, props = {}) {
    const e = document.createElement(tag);
    Object.assign(e.style, style);
    return Object.assign(e, props);
}

app.registerExtension({
    name: "SmartImageTools.ImageComparer",

    setup() {
        api.addEventListener("executed", ({ detail }) => {
            const node = app.graph.getNodeById(Number(detail?.node));
            if (node?.type === "SmartImageComparer") node.showComparison(detail.output);
        });
    },

    nodeCreated(node) {
        if (node.comfyClass !== "SmartImageComparer") return;
        node.properties.target ??= 0;
        node.properties.savePrefix ??= "Compare";
        node.properties.images ??= { a: [], b: [] };

        const root = el("div", { position: "relative", width: "100%", height: "100%", overflow: "hidden", cursor: "col-resize", background: "#111", borderRadius: "4px" });
        const fill = { position: "absolute", inset: "0", width: "100%", height: "100%", objectFit: "contain", pointerEvents: "none" };
        const imgA = el("img", fill);
        const imgB = el("img", { ...fill, clipPath: "inset(0 0 0 100%)" });
        const line = el("div", { position: "absolute", top: "0", bottom: "0", width: "1px", background: "#fff", display: "none", pointerEvents: "none" });
        const tag = { position: "absolute", top: "4px", padding: "1px 6px", font: "11px sans-serif", color: "#fff", background: "rgba(0,0,0,0.6)", borderRadius: "3px", display: "none", pointerEvents: "none" };
        const tagA = el("div", { ...tag, left: "4px" }, { textContent: "A" });
        const tagB = el("div", { ...tag, right: "4px" }, { textContent: "B" });
        const status = el("div", { position: "absolute", bottom: "4px", left: "4px", padding: "2px 6px", font: "11px sans-serif", color: "#fff", background: "rgba(0,0,0,0.6)", borderRadius: "3px", display: "none", pointerEvents: "none" });
        root.append(imgA, imgB, line, tagA, tagB, status);

        let statusTimer;
        function showStatus(text) {
            status.textContent = text;
            status.style.display = "";
            clearTimeout(statusTimer);
            statusTimer = setTimeout(() => (status.style.display = "none"), 3000);
        }

        function slide(e) {
            if (!imgB.src) return;
            const rect = root.getBoundingClientRect();
            const pct = Math.min(100, Math.max(0, ((e.clientX - rect.left) / rect.width) * 100));
            imgB.style.clipPath = `inset(0 0 0 ${pct}%)`;
            line.style.left = `${pct}%`;
            line.style.display = tagA.style.display = tagB.style.display = "";
        }
        root.addEventListener("pointermove", slide);
        root.addEventListener("pointerdown", slide);
        root.addEventListener("pointerleave", () => {
            imgB.style.clipPath = "inset(0 0 0 100%)";
            line.style.display = tagA.style.display = tagB.style.display = "none";
        });
        // No zoom of its own, so the wheel zooms and pans the canvas like it does over a plain node.
        root.addEventListener("wheel", (e) => {
            e.preventDefault();
            e.stopPropagation();
            app.canvas.processMouseWheel(e);
        }, { passive: false });

        function render() {
            const { a, b } = node.properties.images;
            // Without image_b, compare the first two images of image_a.
            const right = b[0] ?? a[1];
            if (a[0]) imgA.src = viewUrl(a[0]); else imgA.removeAttribute("src");
            if (right) imgB.src = viewUrl(right); else imgB.removeAttribute("src");
        }

        node.showComparison = (output) => {
            node.properties.images = { a: output?.a_images ?? [], b: output?.b_images ?? [] };
            render();
        };

        function resolveTarget() {
            const targets = loadImageNodes();
            return targets.find((n) => String(n.id) === String(node.properties.target)) ?? (targets.length === 1 ? targets[0] : null);
        }

        const targetButton = node.addWidget("button", "target", null, () => {
            const targets = loadImageNodes();
            if (!targets.length) return;
            const i = targets.findIndex((n) => String(n.id) === String(node.properties.target));
            node.properties.target = Number(targets[(i + 1) % targets.length].id);
            app.graph.setDirtyCanvas(true, false);
        }, { serialize: false });
        targetButton.serialize = false;
        Object.defineProperty(targetButton, "label", {
            get() {
                const target = resolveTarget();
                return target ? `Target: ${nodeLabel(target)}` : "Target: click to pick Load Image";
            },
            set() {},
        });

        const sendButton = node.addWidget("button", "Send", null, async () => {
            const img = node.properties.images.a[0];
            const target = resolveTarget();
            if (!img) return showStatus("Run the workflow first");
            if (!target) return showStatus("Pick a target Load Image");
            try {
                sendTo(target, await copyImage(img, img.filename, "input", "smart_sends"));
                showStatus(`Sent to ${nodeLabel(target)}`);
            } catch (err) {
                showStatus(err.message);
            }
        }, { serialize: false });
        sendButton.serialize = false;

        const prefixWidget = node.addWidget("text", "save_prefix", node.properties.savePrefix, (v) => (node.properties.savePrefix = v), { serialize: false });
        prefixWidget.serialize = false;

        const saveButton = node.addWidget("button", "Save results", null, async () => {
            const images = node.properties.images.a;
            if (!images.length) return showStatus("Run the workflow first");
            const stamp = timestamp();
            try {
                const saved = [];
                for (const [i, img] of images.entries()) {
                    const suffix = images.length > 1 ? `_${i + 1}` : "";
                    saved.push((await copyImage(img, `${node.properties.savePrefix || "Compare"}_${stamp}${suffix}.png`, "output", "")).filename);
                }
                showStatus(`Saved ${saved.join(", ")}`);
            } catch (err) {
                showStatus(err.message);
            }
        }, { serialize: false });
        saveButton.serialize = false;

        const saveAsButton = node.addWidget("button", "Save as...", null, async () => {
            const images = node.properties.images.a;
            if (!images.length) return showStatus("Run the workflow first");
            if (!window.showDirectoryPicker) return showStatus("This browser can't pick folders, use Chrome or Edge");
            let dir;
            try {
                dir = await pickFolder();
            } catch (err) {
                if (err.name !== "AbortError") showStatus(err.message);
                return;
            }
            const stamp = timestamp();
            try {
                const saved = [];
                for (const [i, img] of images.entries()) {
                    const suffix = images.length > 1 ? `_${i + 1}` : "";
                    const resp = await fetch(viewUrl(img));
                    if (!resp.ok) throw new Error("Image is gone, run the workflow again");
                    const blob = await resp.blob();
                    const name = await freeName(dir, `${node.properties.savePrefix || "Compare"}_${stamp}${suffix}`, ".png");
                    const writable = await (await dir.getFileHandle(name, { create: true })).createWritable();
                    await writable.write(blob);
                    await writable.close();
                    saved.push(name);
                }
                showStatus(`Saved ${saved.join(", ")} to ${dir.name}`);
            } catch (err) {
                showStatus(err.message);
            }
        }, { serialize: false });
        saveAsButton.serialize = false;

        node.addDOMWidget("comparer", "comparer", root, { serialize: false, getMinHeight: () => 200 });

        const onConfigure = node.onConfigure;
        node.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            prefixWidget.value = node.properties.savePrefix;
            render();
        };

        node.setSize([Math.max(node.size[0], 420), Math.max(node.size[1], 460)]);
    },
});
