import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

// Inline mask painter for "Load Image (Mask Paint)". The mask is painted in red over the image at full image
// resolution and uploaded as a greyscale PNG to input/smart_masks, referenced by the hidden mask_file widget.

const NODE_TYPE = "SmartLoadImageMaskPaint";
const UNDO_STEPS = 10;
const pendingSaves = new Set();

function viewUrl(value, channel) {
    let name = value;
    let type = "input";
    const m = value.match(/^(.*) \[(\w+)\]$/);
    if (m) [, name, type] = m;
    const i = name.lastIndexOf("/");
    const params = new URLSearchParams({
        filename: i >= 0 ? name.slice(i + 1) : name,
        subfolder: i >= 0 ? name.slice(0, i) : "",
        type,
        rand: Math.random(),
    });
    if (channel) params.set("channel", channel);
    return api.apiURL(`/view?${params}`);
}

function el(tag, style, props = {}) {
    const e = document.createElement(tag);
    Object.assign(e.style, style);
    return Object.assign(e, props);
}

function button(text, title, onClick) {
    const b = el("button", {
        padding: "2px 7px", fontSize: "12px", borderRadius: "4px", cursor: "pointer",
        border: "1px solid var(--border-color, #555)", background: "var(--comfy-input-bg, #222)", color: "var(--input-text, #ddd)",
    }, { textContent: text, title });
    b.addEventListener("click", onClick);
    return b;
}

function setupPainter(node) {
    const imageWidget = node.widgets.find((w) => w.name === "image");
    const maskWidget = node.widgets.find((w) => w.name === "mask_file");
    maskWidget.hidden = true;
    maskWidget.computeSize = () => [0, -4];
    node.properties.maskKey ??= Math.random().toString(36).slice(2, 10);
    // The painter is the preview. Nodes 2.0 would otherwise add its own below it and squeeze the painter.
    node.hideOutputImages = true;

    let mode = "brush";
    let size = 40;
    let loadedValue = null;
    let stamp = 0;
    let drawing = false;
    let last = null;
    let rectStart = null;
    let resizing = null;
    let saveTimer = null;
    const undo = [];

    const root = el("div", { display: "flex", flexDirection: "column", gap: "4px", width: "100%", height: "100%", boxSizing: "border-box" });
    const bar = el("div", { display: "flex", flexWrap: "wrap", gap: "4px", alignItems: "center", fontSize: "12px", color: "var(--input-text, #ddd)" });
    // The area takes its size from the node only; the stage is absolutely centred so it never feeds back into that size.
    const area = el("div", { flex: "1", minHeight: "0", position: "relative", overflow: "hidden" });
    const stage = el("div", { position: "absolute", left: "50%", top: "50%", transform: "translate(-50%, -50%)", touchAction: "none", cursor: "none" });
    const img = el("img", { display: "block", width: "100%", height: "100%", userSelect: "none", pointerEvents: "none" }, { draggable: false });
    const canvas = el("canvas", { position: "absolute", inset: "0", width: "100%", height: "100%", opacity: "0.5" });
    const cursor = el("div", { position: "absolute", border: "1px solid #fff", outline: "1px solid #000", borderRadius: "50%", pointerEvents: "none", display: "none", transform: "translate(-50%, -50%)" });
    const marquee = el("div", { position: "absolute", border: "1px dashed #fff", outline: "1px dashed #000", pointerEvents: "none", display: "none" });
    const stampBox = el("div", { position: "absolute", border: "1px dashed #0f8", pointerEvents: "none", display: "none", transform: "translate(-50%, -50%)", color: "#0f8", fontSize: "10px", textShadow: "0 0 2px #000" });
    const ctx = canvas.getContext("2d", { willReadFrequently: true });

    const brushBtn = button("Brush", "Paint mask (B). Alt+drag left/right or [ ] to resize.", () => setMode("brush"));
    const eraseBtn = button("Erase", "Erase mask (E). Alt+drag left/right or [ ] to resize.", () => setMode("erase"));
    const rectBtn = button("Rect", "Drag a rectangle to mask it. Shift+drag erases.", () => setMode("rect"));
    const stampSelect = el("select", { fontSize: "12px" }, { title: "Click stamps a square mask of this size (image pixels), centred on the click. Shift+click erases." });
    for (const v of [0, 256, 384, 512, 768, 1024, 1280, 1536, 2048]) stampSelect.append(new Option(v ? `Stamp ${v}²` : "Stamp off", v));
    stampSelect.addEventListener("change", () => {
        stamp = Number(stampSelect.value);
        setMode(stamp ? "stamp" : "brush");
    });
    const sizeInfo = el("span", { marginLeft: "auto", opacity: "0.8" }, { title: "Image size" });
    const sizeInput = el("input", { width: "80px" }, { type: "range", min: 1, max: 1024, value: size, title: "Brush diameter in image pixels (1-1024)" });
    const sizeLabel = el("span", { minWidth: "28px" }, { textContent: size });
    sizeInput.addEventListener("input", () => setSize(Number(sizeInput.value)));
    const showBtn = button("Hide", "Show or hide the mask overlay", () => {
        const hidden = canvas.style.visibility === "hidden";
        canvas.style.visibility = hidden ? "visible" : "hidden";
        showBtn.textContent = hidden ? "Hide" : "Show";
    });
    bar.append(brushBtn, eraseBtn, rectBtn, sizeInput, sizeLabel, stampSelect,
        button("Undo", "Undo last stroke", () => { if (undo.length) { popUndo(); scheduleSave(); } }),
        button("Invert", "Invert the mask", () => {
            pushUndo();
            ctx.globalCompositeOperation = "xor";
            ctx.fillStyle = "#f00";
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.globalCompositeOperation = "source-over";
            scheduleSave();
        }),
        button("Clear", "Clear the mask", () => { pushUndo(); ctx.clearRect(0, 0, canvas.width, canvas.height); scheduleSave(); }),
        showBtn, sizeInfo);
    stage.append(img, canvas, cursor, marquee, stampBox);
    area.append(stage);
    root.append(bar, area);

    // Brush, Erase, Rect and Stamp are exclusive tools; picking another tool turns the stamp off.
    function setMode(m) {
        mode = m;
        if (m !== "stamp") {
            stamp = 0;
            stampSelect.value = "0";
        }
        brushBtn.style.outline = m === "brush" ? "2px solid #e33" : "none";
        eraseBtn.style.outline = m === "erase" ? "2px solid #e33" : "none";
        rectBtn.style.outline = m === "rect" ? "2px solid #e33" : "none";
        stampSelect.style.outline = m === "stamp" ? "2px solid #e33" : "none";
        stage.style.cursor = m === "rect" || m === "stamp" ? "crosshair" : "none";
    }

    function setSize(v) {
        size = Math.max(1, Math.min(1024, Math.round(v)));
        sizeInput.value = size;
        sizeLabel.textContent = size;
    }
    setMode("brush");

    function fit() {
        if (!img.naturalWidth) return;
        const w = area.clientWidth, h = area.clientHeight;
        if (!w || !h) return;
        const s = Math.min(w / img.naturalWidth, h / img.naturalHeight);
        stage.style.width = `${img.naturalWidth * s}px`;
        stage.style.height = `${img.naturalHeight * s}px`;
    }
    new ResizeObserver(fit).observe(area);
    const onResize = node.onResize;
    node.onResize = function () {
        onResize?.apply(this, arguments);
        requestAnimationFrame(fit);
    };

    // Undo keeps only the mask's alpha, a quarter of the full RGBA snapshot, which adds up on 8K images.
    function pushUndo() {
        const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const alpha = new Uint8Array(data.length / 4);
        for (let i = 0; i < alpha.length; i++) alpha[i] = data[i * 4 + 3];
        undo.push(alpha);
        if (undo.length > UNDO_STEPS) undo.shift();
    }

    function popUndo() {
        const alpha = undo.pop();
        const d = new ImageData(canvas.width, canvas.height);
        for (let i = 0; i < alpha.length; i++) {
            d.data[i * 4] = 255;
            d.data[i * 4 + 3] = alpha[i];
        }
        ctx.putImageData(d, 0, 0);
    }

    function toImage(e) {
        const r = canvas.getBoundingClientRect();
        return [(e.clientX - r.left) * canvas.width / r.width, (e.clientY - r.top) * canvas.height / r.height];
    }

    // Stage CSS pixels per image pixel.
    function scale() {
        return stage.offsetWidth / canvas.width;
    }

    function toStage(e) {
        const r = stage.getBoundingClientRect();
        const k = stage.offsetWidth / r.width;
        return [(e.clientX - r.left) * k, (e.clientY - r.top) * k];
    }

    function moveCursor(e) {
        // While Alt-resizing the brush circle stays where the drag started.
        const [x, y] = resizing ? resizing.at : toStage(e);
        const brush = mode === "brush" || mode === "erase";
        const d = size * scale();
        Object.assign(cursor.style, { display: brush ? "block" : "none", left: `${x}px`, top: `${y}px`, width: `${d}px`, height: `${d}px` });
        const g = stamp * scale();
        Object.assign(stampBox.style, { display: mode === "stamp" ? "block" : "none", left: `${x}px`, top: `${y}px`, width: `${g}px`, height: `${g}px` });
        stampBox.textContent = mode === "stamp" ? `${stamp}` : "";
    }

    function rectFrom(a, b) {
        return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
    }

    function fillRect(x, y, w, h, erase) {
        ctx.fillStyle = "#f00";
        if (erase) ctx.clearRect(x, y, w, h);
        else ctx.fillRect(x, y, w, h);
    }

    function stroke(from, to) {
        ctx.globalCompositeOperation = mode === "erase" ? "destination-out" : "source-over";
        ctx.strokeStyle = ctx.fillStyle = "#f00";
        ctx.lineWidth = size;
        ctx.lineCap = ctx.lineJoin = "round";
        ctx.beginPath();
        if (from) {
            ctx.moveTo(...from);
            ctx.lineTo(...to);
            ctx.stroke();
        } else {
            ctx.arc(to[0], to[1], size / 2, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.globalCompositeOperation = "source-over";
    }

    stage.addEventListener("contextmenu", (e) => { if (e.altKey) e.preventDefault(); });
    stage.addEventListener("pointerdown", (e) => {
        if (!img.naturalWidth) return;
        const brush = mode === "brush" || mode === "erase";
        // Photoshop style: Alt + left or right drag resizes the brush.
        if (e.altKey && brush && (e.button === 0 || e.button === 2)) {
            e.stopPropagation();
            e.preventDefault();
            stage.setPointerCapture(e.pointerId);
            resizing = { x: e.clientX, size, at: toStage(e) };
            return;
        }
        if (e.button !== 0) return;
        e.stopPropagation();
        e.preventDefault();
        root.focus({ preventScroll: true });
        stage.setPointerCapture(e.pointerId);
        pushUndo();
        if (mode === "stamp") {
            const [x, y] = toImage(e);
            fillRect(x - stamp / 2, y - stamp / 2, stamp, stamp, e.shiftKey);
            scheduleSave();
            return;
        }
        if (mode === "rect") {
            rectStart = toImage(e);
            return;
        }
        drawing = true;
        last = toImage(e);
        stroke(null, last);
    });
    stage.addEventListener("pointermove", (e) => {
        if (resizing) {
            e.stopPropagation();
            const r = canvas.getBoundingClientRect();
            // Diameter follows the drag distance, measured in image pixels.
            setSize(resizing.size + (e.clientX - resizing.x) * 2 * canvas.width / r.width);
        }
        moveCursor(e);
        if (resizing) return;
        if (rectStart) {
            e.stopPropagation();
            const [x, y, w, h] = rectFrom(rectStart, toImage(e));
            const k = scale();
            Object.assign(marquee.style, { display: "block", left: `${x * k}px`, top: `${y * k}px`, width: `${w * k}px`, height: `${h * k}px` });
            return;
        }
        if (!drawing) return;
        e.stopPropagation();
        const p = toImage(e);
        stroke(last, p);
        last = p;
    });
    const end = (e) => {
        if (resizing) {
            resizing = null;
            moveCursor(e);
            return;
        }
        if (rectStart) {
            const [x, y, w, h] = rectFrom(rectStart, toImage(e));
            if (w * scale() >= 3 && h * scale() >= 3) fillRect(x, y, w, h, e.shiftKey);
            rectStart = null;
            marquee.style.display = "none";
            scheduleSave();
        }
        if (drawing) { drawing = false; scheduleSave(); }
    };
    stage.addEventListener("pointerup", end);
    stage.addEventListener("pointercancel", end);
    stage.addEventListener("pointerleave", () => { if (!resizing) cursor.style.display = stampBox.style.display = "none"; });
    root.addEventListener("keydown", (e) => {
        if (e.key === "b") setMode("brush");
        if (e.key === "e") setMode("erase");
        if (e.key === "r") setMode("rect");
        if (e.key === "[") setSize(size * 0.85);
        if (e.key === "]") setSize(size / 0.85 + 1);
    });
    root.tabIndex = 0;
    // The painter has no zoom of its own, so the wheel zooms and pans the canvas like it does over a plain node.
    root.addEventListener("wheel", (e) => {
        e.preventDefault();
        e.stopPropagation();
        app.canvas.processMouseWheel(e);
    }, { passive: false });

    // Debounced; one pending promise per painter so a re-scheduled save never leaves a promise that cannot settle.
    let pending = null;
    let settle = null;
    function scheduleSave() {
        clearTimeout(saveTimer);
        if (!pending) {
            pending = new Promise((r) => (settle = r));
            pendingSaves.add(pending);
        }
        saveTimer = setTimeout(() => {
            const p = pending, done = settle;
            pending = settle = null;
            save().catch(console.error).finally(() => { pendingSaves.delete(p); done(); });
        }, 300);
    }

    async function save() {
        const { width, height } = canvas;
        const src = ctx.getImageData(0, 0, width, height).data;
        const out = new ImageData(width, height);
        let any = false;
        for (let i = 0; i < src.length; i += 4) {
            const a = src[i + 3];
            if (a) any = true;
            out.data[i] = out.data[i + 1] = out.data[i + 2] = a;
            out.data[i + 3] = 255;
        }
        if (!any) {
            maskWidget.value = "";
            return;
        }
        const tmp = el("canvas", {}, { width, height });
        tmp.getContext("2d").putImageData(out, 0, 0);
        const blob = await new Promise((r) => tmp.toBlob(r, "image/png"));
        const body = new FormData();
        // The node id keeps two painters apart when the key was copied along with the node.
        body.append("image", blob, `mask_${node.properties.maskKey}_${node.id}.png`);
        body.append("subfolder", "smart_masks");
        body.append("type", "input");
        body.append("overwrite", "true");
        const resp = await api.fetchApi("/upload/image", { method: "POST", body });
        if (resp.status !== 200) return;
        const data = await resp.json();
        maskWidget.value = data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
        node.properties.maskImage = imageWidget.value;
    }

    function loadMask(value) {
        const m = new Image();
        m.onload = () => {
            const tmp = el("canvas", {}, { width: canvas.width, height: canvas.height });
            const t = tmp.getContext("2d");
            t.drawImage(m, 0, 0, canvas.width, canvas.height);
            const d = t.getImageData(0, 0, canvas.width, canvas.height);
            for (let i = 0; i < d.data.length; i += 4) {
                d.data[i + 3] = d.data[i];
                d.data[i] = 255;
                d.data[i + 1] = d.data[i + 2] = 0;
            }
            ctx.putImageData(d, 0, 0);
        };
        m.src = viewUrl(value);
    }

    // Start from the image's own alpha mask (transparent = masked) so it can be seen and edited.
    function loadAlphaMask(value) {
        const a = new Image();
        a.onload = () => {
            const tmp = el("canvas", {}, { width: canvas.width, height: canvas.height });
            const t = tmp.getContext("2d");
            t.drawImage(a, 0, 0, canvas.width, canvas.height);
            const d = t.getImageData(0, 0, canvas.width, canvas.height);
            for (let i = 0; i < d.data.length; i += 4) {
                d.data[i + 3] = 255 - d.data[i + 3];
                d.data[i] = 255;
                d.data[i + 1] = d.data[i + 2] = 0;
            }
            ctx.putImageData(d, 0, 0);
        };
        a.src = viewUrl(value, "a");
    }

    // Follow the image widget however it changes: picker, upload, drag-drop, Send to Load Image or workflow load.
    function syncImage() {
        const value = imageWidget.value;
        if (!value || value === loadedValue) return;
        loadedValue = value;
        img.onload = () => {
            const keep = maskWidget.value && node.properties.maskImage === value;
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            sizeInfo.textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
            undo.length = 0;
            if (keep) {
                loadMask(maskWidget.value);
            } else {
                maskWidget.value = "";
                node.properties.maskImage = value;
                loadAlphaMask(value);
            }
            requestAnimationFrame(fit);
        };
        // A drag-drop sets the widget before its upload has finished, so the first request can miss the file.
        let retries = 0;
        img.onerror = () => {
            if (retries++ < 10) setTimeout(() => { if (loadedValue === value) img.src = viewUrl(value, "rgb"); }, 300);
        };
        img.src = viewUrl(value, "rgb");
    }

    const callback = imageWidget.callback;
    imageWidget.callback = function () {
        const r = callback?.apply(this, arguments);
        syncImage();
        return r;
    };
    const onConfigure = node.onConfigure;
    node.onConfigure = function () {
        onConfigure?.apply(this, arguments);
        syncImage();
    };
    // The painter is the preview. Skip the default onDrawBackground: it adds a $$canvas-image-preview widget
    // whenever node.imgs is set, and that widget splits the node's free height with the painter.
    node.onDrawBackground = function () {
        const i = this.widgets.findIndex((w) => w.name === "$$canvas-image-preview");
        if (i >= 0) {
            this.widgets[i].onRemove?.();
            this.widgets.splice(i, 1);
        }
        syncImage();
    };

    // The painter covers the node, so file drops land on it instead of the canvas; hand them to the node's
    // own Load Image drop handlers.
    root.addEventListener("dragover", (e) => {
        if (!node.onDragOver?.(e)) return;
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "copy";
    });
    root.addEventListener("drop", (e) => {
        if (!node.onDragOver?.(e)) return;
        e.preventDefault();
        e.stopPropagation();
        node.onDragDrop?.(e);
    });
    syncImage();

    node.addDOMWidget("mask_painter", "mask_painter", root, { serialize: false, getMinHeight: () => 220 });
    node.setSize([Math.max(node.size[0], 420), Math.max(node.size[1], 480)]);
}

app.registerExtension({
    name: "SmartImageTools.MaskPaint",

    setup() {
        // Make sure the latest strokes are uploaded before the prompt is built.
        const graphToPrompt = app.graphToPrompt;
        app.graphToPrompt = async function () {
            await Promise.all([...pendingSaves]);
            return graphToPrompt.apply(this, arguments);
        };
    },

    nodeCreated(node) {
        if (node.comfyClass === NODE_TYPE) setupPainter(node);
    },
});
