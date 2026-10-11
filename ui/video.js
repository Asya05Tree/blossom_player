function setVideoSource(src) {
    const container = document.getElementById("video-container");
    if (!container) return;

    // file:/// URL — custom background from settings
    if (src && src.startsWith("file:///")) {
        container.innerHTML =
            '<video src="' + src + '" autoplay loop muted playsinline ' +
            'style="width:100%; height:100%; object-fit:cover;"></video>';
        return;
    }

    // .webm or .mp4 relative path
    if (src && (src.endsWith(".webm") || src.endsWith(".mp4"))) {
        container.innerHTML =
            '<video src="../' + src + '" autoplay loop muted playsinline ' +
            'style="width:100%; height:100%; object-fit:cover;"></video>';
        return;
    }

    // Default: bg.webm
    container.innerHTML =
        '<video src="../bg.webm" autoplay loop muted playsinline ' +
        'style="width:100%; height:100%; object-fit:cover;"></video>';
}
