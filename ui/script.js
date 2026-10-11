let pyBridge = null;
let isPlaying = false;
let currentLoopMode = "sequence";
let librarySongs = [];
let playlists = [];
let selectedSongId = null;

var driveLoggedIn = false;

document.addEventListener("DOMContentLoaded", function() {
    var savedVideo = localStorage.getItem("blossom_video_bg");
    setVideoSource(savedVideo || "bg.webm");
    new QWebChannel(qt.webChannelTransport, function(channel) {
        pyBridge = channel.objects.pyBridge;
        wireBridgeSignals();
        setVolume(20);
        setPlayIcon(false);
        updateLoopLabel();
        updateShuffleLabel();
        checkDriveOnStartup();
    });
});

function checkDriveOnStartup() {
    if (!pyBridge) return;
    setDriveOverlayMode("checking");
    // Настоящая проверка доступа (реальный вызов Drive API в фоне),
    // а не просто наличие token.json
    if (pyBridge.checkDriveAccess) {
        pyBridge.checkDriveAccess();
    } else if (pyBridge.emitDriveStatus) {
        pyBridge.emitDriveStatus();
    }
}

// Оверлей входа: "checking" — идёт проверка (без кнопок), "login" — предложение войти
function setDriveOverlayMode(mode) {
    var sub = document.getElementById("drive-login-sub");
    var actions = document.getElementById("drive-login-actions");
    var status = document.getElementById("drive-login-status");
    if (mode === "checking") {
        if (sub) sub.innerText = "Проверяю доступ к Google Drive…";
        if (actions) actions.style.display = "none";
        if (status) { status.innerText = ""; status.className = "drive-login-status"; }
    } else {
        if (sub) sub.innerText = "Войди в Google Drive чтобы начать";
        if (actions) actions.style.display = "block";
    }
}

function onDriveReady(data) {
    driveLoggedIn = true;
    document.getElementById("drive-login-overlay").classList.add("hidden");
    refreshDriveStatus();
    if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
    if (pyBridge.syncFromDrive) pyBridge.syncFromDrive();
}

function wireBridgeSignals() {
    pyBridge.songChanged.connect(function(title, artist, cover, lyrics, video, playlists, has_prev, has_next) {
        document.getElementById("title").innerText = title;
        document.getElementById("artist").innerText = artist;
        document.getElementById("lyrics").innerText = lyrics;
        document.getElementById("cover").src = resolveCoverSrc(cover);
        const bp = document.getElementById("btn-prev");
        const bn = document.getElementById("btn-next");
        if (bp) bp.disabled = !has_prev;
        if (bn) bn.disabled = !has_next;
        if (video && video.trim() !== "") {
            setVideoSource(video.trim());
        } else {
            var custom = localStorage.getItem("blossom_video_bg");
            setVideoSource(custom || "bg.webm");
        }
    });

    if (pyBridge.nextSongPreview) {
        pyBridge.nextSongPreview.connect(function(nextTitle) {
            document.getElementById("next-preview").innerText = nextTitle;
        });
    }

    if (pyBridge.libraryUpdated) {
        pyBridge.libraryUpdated.connect(function(json) {
            renderLibrary(json);
        });
    }

    if (pyBridge.playlistListUpdated) {
        pyBridge.playlistListUpdated.connect(function(list) {
            playlists = list || [];
            renderPlaylists();
        });
    }

    if (pyBridge.filePicked) {
        pyBridge.filePicked.connect(function(path, kind) {
            onFilePicked(path, kind);
        });
    }

    if (pyBridge.toastMessage) {
        pyBridge.toastMessage.connect(function(msg, isError) {
            showToast(msg, isError);
        });
    }

    if (pyBridge.driveStatusChanged) {
        pyBridge.driveStatusChanged.connect(applyDriveStatus);
    }

    if (pyBridge.driveLoginFailed) {
        pyBridge.driveLoginFailed.connect(function(stage, code, message) {
            var text = message;
            if (code === "GOOGLE_TEST_USER_REQUIRED") {
                text = "Опубликуй приложение (Production) или добавь Gmail в Test users.";
            }
            setDriveOverlayMode("login");
            var loginStatus = document.getElementById("drive-login-status");
            if (loginStatus) { loginStatus.innerText = text; loginStatus.className = "drive-login-status error"; }
            showToast(text, true);
        });
    }

    if (pyBridge.importStarted) {
        pyBridge.importStarted.connect(function() {
            setImportStatus("Скачивание… подожди 1–5 мин", false);
            setImportLock(true);
        });
    }

    if (pyBridge.importFinished) {
        pyBridge.importFinished.connect(function(title) {
            setImportStatus("Готово: " + title, false, true);
            setImportLock(false);
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.importFailed) {
        pyBridge.importFailed.connect(function(stage, code, message) {
            setImportStatus("[" + stage + ":" + code + "] " + message, true);
            setImportLock(false);
        });
    }

    if (pyBridge.importProgress) {
        pyBridge.importProgress.connect(function(msg) {
            setImportStatus(msg, false);
        });
    }

    if (pyBridge.spotifyAutoProgress) {
        pyBridge.spotifyAutoProgress.connect(function(msg) {
            appendSpotifyAutoLog(msg);
            setSpotifyAutoStatus(msg, false);
        });
    }

    if (pyBridge.spotifyAutoFinished) {
        pyBridge.spotifyAutoFinished.connect(function(msg) {
            appendSpotifyAutoLog(msg);
            setSpotifyAutoStatus(msg, false, true);
            setSpotifyAutoLock(false);
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.spotifyAutoFailed) {
        pyBridge.spotifyAutoFailed.connect(function(msg) {
            appendSpotifyAutoLog(msg);
            setSpotifyAutoStatus(msg, true);
            setSpotifyAutoLock(false);
        });
    }

    if (pyBridge.songForEditReady) {
        pyBridge.songForEditReady.connect(function(json) {
            _populateEditModal(json);
        });
    }

    if (pyBridge.positionChanged) {
        pyBridge.positionChanged.connect(function(pos, dur) {
            updateProgressBar(pos, dur);
        });
    }
}

function resolveCoverSrc(cover) {
    if (!cover) return "../assets/default_cover.png";
    if (cover.startsWith("file:///")) return cover;
    return cover;
}

function showToast(msg, isError) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.innerText = msg;
    el.className = "toast" + (isError ? " error" : "");
    clearTimeout(el._timer);
    el._timer = setTimeout(function() { el.className = "toast hidden"; }, 3500);
}

function onFilePicked(path, kind) {
    if (!path) return;
    if (kind === "audio") {
        document.getElementById("modal-path").value = path;
        const base = path.split(/[/\\]/).pop().replace(/\.[^.]+$/, "");
        const t = document.getElementById("modal-title");
        if (t && !t.value.trim()) t.value = base;
    } else if (kind === "cover" || kind === "cover_local") {
        const id = kind === "cover" ? "spotify-cover" : "modal-cover";
        document.getElementById(id).value = path;
    } else if (kind === "cover_edit") {
        document.getElementById("edit-cover-path").value = path;
        document.getElementById("edit-cover-preview").src = "file:///" + path.replace(/\\/g, "/");
    } else if (kind === "video_bg") {
        document.getElementById("settings-video-path").value = path;
    }
}

function pickFile(kind) {
    if (pyBridge && pyBridge.pickFile) pyBridge.pickFile(kind);
}

function renderLibrary(json) {
    try {
        librarySongs = typeof json === "string" ? JSON.parse(json) : json;
    } catch (e) {
        librarySongs = [];
    }
    const list = document.getElementById("song-list");
    if (!list) return;
    list.innerHTML = "";
    if (!librarySongs.length) {
        list.innerHTML = "<p style='font-size:12px;color:#9a86a4;padding:8px'>Пока нет треков</p>";
        return;
    }
    librarySongs.forEach(function(s) {
        const row = document.createElement("div");
        row.className = "song-item";
        const cover = s.cover || "../assets/default_cover.png";
        row.innerHTML =
            "<img src='" + cover + "' alt=''>" +
            "<div class='song-item-info'>" +
            "<div class='song-item-title'>" + escapeHtml(s.title_raw || s.title) + "</div>" +
            "<div class='song-item-artist'>" + escapeHtml(s.artist_raw || s.artist) + "</div>" +
            "</div>" +
            "<div class='song-item-actions'>" +
            "<button type='button' data-play='" + s.id + "'>Play</button>" +
            "<button type='button' data-playlist='" + s.id + "'>Плейлист</button>" +
            "<button type='button' data-edit='" + s.id + "'>Изм.</button>" +
            "<button type='button' data-del='" + s.id + "'>Удал.</button>" +
            "</div>";
        list.appendChild(row);
    });
    list.querySelectorAll("[data-play]").forEach(function(btn) {
        btn.onclick = function() {
            selectedSongId = parseInt(btn.getAttribute("data-play"));
            pyBridge.playSongById(selectedSongId);
            isPlaying = true;
            setPlayIcon(true);
        };
    });
    list.querySelectorAll("[data-playlist]").forEach(function(btn) {
        btn.onclick = function() { openPlaylistModal(parseInt(btn.getAttribute("data-playlist"))); };
    });
    list.querySelectorAll("[data-edit]").forEach(function(btn) {
        btn.onclick = function() { openEditModal(parseInt(btn.getAttribute("data-edit"))); };
    });
    list.querySelectorAll("[data-del]").forEach(function(btn) {
        btn.onclick = function() {
            if (confirm("Удалить этот трек?")) pyBridge.deleteSongById(parseInt(btn.getAttribute("data-del")));
        };
    });
}

function escapeHtml(t) {
    return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function renderPlaylists() {
    const list = document.getElementById("playlist-list");
    if (!list) return;
    list.innerHTML = "";
    playlists.forEach(function(p) {
        const row = document.createElement("div");
        row.className = "playlist-item";
        row.innerHTML = "<span class='pl-name' data-viewpl='" + p.id + "' data-plname='" + escapeHtml(p.name) + "'>" + escapeHtml(p.name) + "</span>" +
            "<span>" +
            "<button type='button' data-playpl='" + p.id + "' title='Воспроизвести'>&#9654;</button> " +
            "<button type='button' data-renamepl='" + p.id + "' title='Переименовать'>&#9998;</button> " +
            "<button type='button' data-delpl='" + p.id + "' title='Удалить'>&times;</button>" +
            "</span>";
        list.appendChild(row);
    });
    list.querySelectorAll("[data-viewpl]").forEach(function(el) {
        el.onclick = function() { openPlaylistView(parseInt(el.getAttribute("data-viewpl")), el.getAttribute("data-plname")); };
        el.style.cursor = "pointer";
    });
    list.querySelectorAll("[data-playpl]").forEach(function(btn) {
        btn.onclick = function() { pyBridge.playPlaylist(parseInt(btn.getAttribute("data-playpl"))); isPlaying = true; setPlayIcon(true); };
    });
    list.querySelectorAll("[data-renamepl]").forEach(function(btn) {
        btn.onclick = function() { openRenamePl(parseInt(btn.getAttribute("data-renamepl"))); };
    });
    list.querySelectorAll("[data-delpl]").forEach(function(btn) {
        btn.onclick = function() {
            if (confirm("Удалить плейлист?")) pyBridge.deletePlaylistById(parseInt(btn.getAttribute("data-delpl")));
        };
    });
}

function createPlaylist() {
    const name = document.getElementById("new-playlist-name").value;
    if (pyBridge) pyBridge.createPlaylist(name);
    document.getElementById("new-playlist-name").value = "";
}

function toggleLibrary() {
    var panel = document.getElementById("library-panel");
    var label = document.getElementById("library-show");
    panel.classList.toggle("hidden");
    if (panel.classList.contains("hidden")) {
        if (label) label.classList.remove("hidden");
    } else {
        if (label) label.classList.add("hidden");
    }
}

function openEditModal(songId) {
    selectedSongId = songId;
    if (pyBridge.requestSongForEdit) {
        pyBridge.requestSongForEdit(songId);
    }
}

function _populateEditModal(json) {
    var data = {};
    try { data = typeof json === "string" ? JSON.parse(json) : json; } catch (e) { return; }
    if (!data.id) return;
    document.getElementById("edit-song-id").value = data.id;
    document.getElementById("edit-title").value = data.title || "";
    document.getElementById("edit-artist").value = data.artist || "";
    document.getElementById("edit-lyrics").value = data.lyrics || "";
    document.getElementById("edit-cover-path").value = "";
    var coverPreview = document.getElementById("edit-cover-preview");
    if (coverPreview) coverPreview.src = resolveCoverSrc(data.cover);
    document.getElementById("edit-song-modal").style.display = "flex";
}

function saveEditSong() {
    var id = parseInt(document.getElementById("edit-song-id").value);
    if (!id || !pyBridge) return;
    var title = document.getElementById("edit-title").value;
    var artist = document.getElementById("edit-artist").value;
    var lyrics = document.getElementById("edit-lyrics").value;
    var coverPath = document.getElementById("edit-cover-path").value;
    pyBridge.updateSongById(id, title, artist, lyrics, coverPath);
    closeEditModal();
}

function closeEditModal() {
    document.getElementById("edit-song-modal").style.display = "none";
}

function refreshDriveStatus() {
    if (!pyBridge || !pyBridge.emitDriveStatus) return;
    pyBridge.emitDriveStatus();
}

function applyDriveStatus(json) {
    var data = {};
    try { data = typeof json === "string" ? JSON.parse(json) : json; } catch(e) {}
    // Update settings modal status
    var el = document.getElementById("drive-status-text");
    if (el) {
        if (data.logged_in && data.email) el.innerText = "Google Drive: " + data.email;
        else if (data.logged_in) el.innerText = "Google Drive: подключён";
        else el.innerText = "Google Drive: не подключён";
    }
    // Handle login overlay
    if (data.logged_in && !driveLoggedIn) {
        onDriveReady(data);
    }
    if (!data.logged_in && driveLoggedIn) {
        driveLoggedIn = false;
        document.getElementById("drive-login-overlay").classList.remove("hidden");
    }
    // Update login overlay status
    var loginStatus = document.getElementById("drive-login-status");
    if (data.logged_in) {
        if (loginStatus) {
            loginStatus.innerText = "Подключено: " + (data.email || "");
            loginStatus.className = "drive-login-status";
        }
    } else {
        // Проверка завершилась: доступа нет — теперь показываем кнопки входа
        setDriveOverlayMode("login");
        if (loginStatus) {
            loginStatus.innerText = "Нет доступа к Google Drive — войди в аккаунт";
            loginStatus.className = "drive-login-status";
        }
    }
}

function setImportLock(locked) {
    var btn = document.getElementById("btn-spotify-import");
    if (btn) btn.disabled = locked;
    // Lock inputs so values are frozen during download
    var ids = ["spotify-url", "spotify-lyrics", "spotify-cover"];
    ids.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.readOnly = locked;
    });
    // Stop playback icon
    if (locked) {
        isPlaying = false;
        setPlayIcon(false);
    }
}

function setImportStatus(text, isError, isOk) {
    const el = document.getElementById("import-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

function setPlayIcon(playing) {
    const icon = document.getElementById("play-icon");
    if (!icon) return;
    icon.className = playing ? "ico ico-pause" : "ico ico-play";
}

function updateLoopLabel() {
    const el = document.getElementById("loop-label");
    if (!el) return;
    if (currentLoopMode === "repeat_one") el.innerText = "Одна";
    else if (currentLoopMode === "repeat_all") el.innerText = "Все";
    else el.innerText = "По порядку";
}

function updateShuffleLabel() {
    const btn = document.getElementById("btn-shuffle");
    const el = document.getElementById("shuffle-label");
    if (el) el.innerText = btn && btn.classList.contains("btn-active") ? "Микс вкл" : "Перемешать";
}

function togglePlay() {
    if (!pyBridge) return;
    if (isPlaying) { pyBridge.pause(); setPlayIcon(false); }
    else { pyBridge.play(); setPlayIcon(true); }
    isPlaying = !isPlaying;
}

function stopTrack() {
    if (pyBridge) { pyBridge.restart(); isPlaying = true; setPlayIcon(true); }
}

function nextTrack() { if (pyBridge) pyBridge.next(); }
function prevTrack() { if (pyBridge) pyBridge.prev(); }
function setVolume(value) { if (pyBridge) pyBridge.setVolume(parseInt(value)); }

function toggleShuffle() {
    if (pyBridge) {
        pyBridge.toggleShuffle();
        document.getElementById("btn-shuffle").classList.toggle("btn-active");
        updateShuffleLabel();
    }
}

function cycleLoopMode() {
    if (!pyBridge) return;
    const btn = document.getElementById("btn-loop");
    if (currentLoopMode === "sequence") {
        currentLoopMode = "repeat_one";
        btn.classList.add("btn-active");
    } else if (currentLoopMode === "repeat_one") {
        currentLoopMode = "repeat_all";
    } else {
        currentLoopMode = "sequence";
        btn.classList.remove("btn-active");
    }
    updateLoopLabel();
    pyBridge.setLoopMode(currentLoopMode);
}

function toggleSidePanel() {
    document.getElementById("side-panel").classList.toggle("hidden");
}

function toggleAddMenu() {
    document.getElementById("add-menu").classList.toggle("hidden");
}

function openLocalAdd() {
    document.getElementById("add-menu").classList.add("hidden");
    document.getElementById("modal-path").value = "";
    document.getElementById("modal-title").value = "";
    document.getElementById("modal-artist").value = "";
    document.getElementById("modal-lyrics").value = "";
    document.getElementById("modal-cover").value = "";
    toggleAddModal();
}

function openCloudModal() {
    document.getElementById("add-menu").classList.add("hidden");
    document.getElementById("spotify-url").value = "";
    document.getElementById("spotify-lyrics").value = "";
    document.getElementById("spotify-cover").value = "";
    const m = document.getElementById("cloud-modal");
    m.style.display = "flex";
    setImportStatus("");
    refreshDriveStatus();
}

function closeCloudModal() {
    document.getElementById("cloud-modal").style.display = "none";
}

function toggleAddModal() {
    const m = document.getElementById("add-track-modal");
    const open = m.style.display === "none" || !m.style.display;
    m.style.display = open ? "flex" : "none";
}

function loginDrive(pickAccount) {
    if (!pyBridge) return;
    var loginStatus = document.getElementById("drive-login-status");
    if (loginStatus) { loginStatus.innerText = "Откроется браузер — выбери свою Gmail..."; loginStatus.className = "drive-login-status"; }
    pyBridge.loginGoogleDrive(!!pickAccount);
}

function logoutDrive() {
    if (pyBridge) pyBridge.logoutGoogleDrive();
    driveLoggedIn = false;
    document.getElementById("drive-login-overlay").classList.remove("hidden");
}

function cleanSpotifyUrl(raw) {
    const text = (raw || "").trim();
    const re = /https?:\/\/open\.spotify\.com\/(?:intl-[a-z]{2}\/)?track\/[A-Za-z0-9]{22}/gi;
    const matches = text.match(re);
    return matches && matches.length ? matches[matches.length - 1] : text;
}

function submitSpotifyImport() {
    const url = cleanSpotifyUrl(document.getElementById("spotify-url").value);
    document.getElementById("spotify-url").value = url;
    if (!url || !url.includes("open.spotify.com")) {
        setImportStatus("Нужна ссылка Spotify track", true);
        return;
    }
    pyBridge.importFromSpotify(
        url,
        document.getElementById("spotify-lyrics").value,
        document.getElementById("spotify-cover").value.trim(),
        document.getElementById("spotify-upload-drive").checked
    );
}

/* === Spotify Auto Import === */

var spotifyAutoRunning = false;

function openSpotifyAutoModal() {
    document.getElementById("add-menu").classList.add("hidden");
    document.getElementById("spotify-auto-modal").style.display = "flex";
    if (!spotifyAutoRunning) {
        setSpotifyAutoStatus("", false);
    }
}

function closeSpotifyAutoModal() {
    // Импорт продолжается в фоне, окно можно скрыть
    document.getElementById("spotify-auto-modal").style.display = "none";
}

function startSpotifyAutoImport() {
    if (!pyBridge || !pyBridge.importSpotifyLibrary) return;
    if (spotifyAutoRunning) return;
    document.getElementById("spotify-auto-log").innerText = "";
    appendSpotifyAutoLog("Начинаю импорт из Spotify…");
    setSpotifyAutoLock(true);
    pyBridge.importSpotifyLibrary();
}

function stopSpotifyAutoImport() {
    if (pyBridge && pyBridge.stopSpotifyLibraryImport) pyBridge.stopSpotifyLibraryImport();
}

function setSpotifyAutoLock(locked) {
    spotifyAutoRunning = locked;
    var startBtn = document.getElementById("btn-spotify-auto-start");
    var stopBtn = document.getElementById("btn-spotify-auto-stop");
    if (startBtn) startBtn.disabled = locked;
    if (stopBtn) stopBtn.disabled = !locked;
    if (locked) {
        isPlaying = false;
        setPlayIcon(false);
    }
}

function appendSpotifyAutoLog(msg) {
    var log = document.getElementById("spotify-auto-log");
    if (!log || !msg) return;
    var line = document.createElement("div");
    line.innerText = msg;
    log.appendChild(line);
    while (log.childNodes.length > 300) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
}

function setSpotifyAutoStatus(text, isError, isOk) {
    var el = document.getElementById("spotify-auto-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

/* === Playlist Modal === */
var plModalChecked = {};

function openPlaylistModal(songId) {
    document.getElementById("pl-modal-song-id").value = songId;
    document.getElementById("pl-modal-new-name").value = "";
    var listEl = document.getElementById("pl-modal-list");
    listEl.innerHTML = "<p style='font-size:12px;color:#9a86a4'>Загрузка...</p>";
    document.getElementById("playlist-modal").style.display = "flex";
    plModalChecked = {};
    if (pyBridge && pyBridge.getPlaylistsForSongJson) {
        var raw = pyBridge.getPlaylistsForSongJson(songId);
        _renderPlModalList(raw);
    }
}

function _renderPlModalList(json) {
    var data = [];
    try { data = typeof json === "string" ? JSON.parse(json) : json; } catch(e) {}
    var listEl = document.getElementById("pl-modal-list");
    listEl.innerHTML = "";
    if (!data.length) {
        listEl.innerHTML = "<p style='font-size:12px;color:#9a86a4'>Нет плейлистов — создай новый</p>";
        return;
    }
    data.forEach(function(p) {
        plModalChecked[p.id] = p.has_song;
        var row = document.createElement("label");
        row.className = "pl-modal-row";
        row.innerHTML = "<input type='checkbox' data-plid='" + p.id + "' " + (p.has_song ? "checked" : "") + "> " + escapeHtml(p.name);
        listEl.appendChild(row);
    });
    listEl.querySelectorAll("input[data-plid]").forEach(function(cb) {
        cb.onchange = function() { plModalChecked[parseInt(cb.getAttribute("data-plid"))] = cb.checked; };
    });
}

function plModalCreateAndAdd() {
    var name = document.getElementById("pl-modal-new-name").value.trim();
    if (!name) { showToast("Введи название", true); return; }
    if (pyBridge) pyBridge.createPlaylist(name);
    document.getElementById("pl-modal-new-name").value = "";
    setTimeout(function() {
        var songId = parseInt(document.getElementById("pl-modal-song-id").value);
        if (pyBridge && pyBridge.getPlaylistsForSongJson) {
            _renderPlModalList(pyBridge.getPlaylistsForSongJson(songId));
        }
    }, 300);
}

function plModalSave() {
    var songId = parseInt(document.getElementById("pl-modal-song-id").value);
    if (!songId || !pyBridge) return;
    Object.keys(plModalChecked).forEach(function(plId) {
        var id = parseInt(plId);
        if (plModalChecked[id]) {
            pyBridge.addSongToPlaylist(id, songId);
        } else {
            pyBridge.removeSongFromPlaylist(id, songId);
        }
    });
    closePlModal();
    showToast("Плейлисты обновлены", false);
}

function closePlModal() {
    document.getElementById("playlist-modal").style.display = "none";
}

/* === Playlist View === */

function openPlaylistView(playlistId, name) {
    document.getElementById("pv-playlist-id").value = playlistId;
    document.getElementById("pv-title").innerText = name || "Плейлист";
    var listEl = document.getElementById("pv-song-list");
    listEl.innerHTML = "<p style='font-size:12px;color:#9a86a4'>Загрузка...</p>";
    document.getElementById("playlist-view-modal").style.display = "flex";
    if (pyBridge && pyBridge.getPlaylistSongsJson) {
        var raw = pyBridge.getPlaylistSongsJson(playlistId);
        _renderPlaylistViewSongs(raw, playlistId);
    }
}

function _renderPlaylistViewSongs(json, playlistId) {
    var data = [];
    try { data = typeof json === "string" ? JSON.parse(json) : json; } catch(e) {}
    var listEl = document.getElementById("pv-song-list");
    listEl.innerHTML = "";
    if (!data.length) {
        listEl.innerHTML = "<p style='font-size:12px;color:#9a86a4'>Плейлист пуст</p>";
        return;
    }
    data.forEach(function(s) {
        var row = document.createElement("div");
        row.className = "pv-song-row";
        var cover = s.cover || "../assets/default_cover.png";
        row.innerHTML =
            "<img src='" + cover + "' alt=''>" +
            "<div class='pv-song-info'>" +
            "<div class='pv-song-title'>" + escapeHtml(s.title_raw || s.title) + "</div>" +
            "<div class='pv-song-artist'>" + escapeHtml(s.artist_raw || s.artist) + "</div>" +
            "</div>" +
            "<div class='pv-song-actions'>" +
            "<button type='button' data-pvremove='" + s.id + "'>Убрать</button>" +
            "</div>";
        listEl.appendChild(row);
    });
    listEl.querySelectorAll("[data-pvremove]").forEach(function(btn) {
        btn.onclick = function() {
            var songId = parseInt(btn.getAttribute("data-pvremove"));
            pyBridge.removeSongFromPlaylist(playlistId, songId);
            btn.closest(".pv-song-row").remove();
        };
    });
}

function playCurrentPlaylist() {
    var plId = parseInt(document.getElementById("pv-playlist-id").value);
    if (pyBridge && plId) { pyBridge.playPlaylist(plId); isPlaying = true; setPlayIcon(true); }
    closePlaylistView();
}

function closePlaylistView() {
    document.getElementById("playlist-view-modal").style.display = "none";
}

/* === Rename Playlist === */

function openRenamePl(playlistId) {
    document.getElementById("rename-pl-id").value = playlistId;
    document.getElementById("rename-pl-name").value = "";
    document.getElementById("rename-playlist-modal").style.display = "flex";
}

function submitRenamePl() {
    var id = parseInt(document.getElementById("rename-pl-id").value);
    var name = document.getElementById("rename-pl-name").value.trim();
    if (!name) { showToast("Введи название", true); return; }
    if (pyBridge) pyBridge.renamePlaylist(id, name);
    document.getElementById("rename-playlist-modal").style.display = "none";
}

/* === Settings Modal === */

function openSettingsModal() {
    document.getElementById("settings-modal").style.display = "flex";
    refreshDriveStatus();
}

function syncFromDrive() {
    if (pyBridge && pyBridge.syncFromDrive) {
        pyBridge.syncFromDrive();
    }
}

function applySettings() {
    var path = document.getElementById("settings-video-path").value.trim();
    if (path) {
        var url = "file:///" + path.replace(/\\/g, "/");
        setVideoSource(url);
        localStorage.setItem("blossom_video_bg", url);
    }
    document.getElementById("settings-modal").style.display = "none";
    showToast("Настройки применены", false);
}

/* === Progress Bar === */

var isSeeking = false;

function formatTime(ms) {
    var s = Math.floor(ms / 1000);
    var m = Math.floor(s / 60);
    s = s % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
}

function updateProgressBar(pos, dur) {
    if (isSeeking) return;
    var slider = document.getElementById("progress-slider");
    var cur = document.getElementById("time-current");
    var tot = document.getElementById("time-total");
    if (!slider) return;
    if (dur > 0) {
        slider.value = Math.round((pos / dur) * 1000);
    } else {
        slider.value = 0;
    }
    if (cur) cur.innerText = formatTime(pos);
    if (tot) tot.innerText = formatTime(dur);
}

function onSeek(value) {
    isSeeking = true;
    var slider = document.getElementById("progress-slider");
    var cur = document.getElementById("time-current");
    var tot = document.getElementById("time-total");
    var durText = tot ? tot.innerText : "0:00";
    var parts = durText.split(":");
    var durSec = parseInt(parts[0]) * 60 + parseInt(parts[1] || 0);
    var posSec = (parseInt(value) / 1000) * durSec;
    if (cur) cur.innerText = formatTime(posSec * 1000);
}

document.addEventListener("mouseup", function() {
    if (!isSeeking) return;
    isSeeking = false;
    var slider = document.getElementById("progress-slider");
    if (!slider || !pyBridge) return;
    var tot = document.getElementById("time-total");
    var durText = tot ? tot.innerText : "0:00";
    var parts = durText.split(":");
    var durMs = (parseInt(parts[0]) * 60 + parseInt(parts[1] || 0)) * 1000;
    var posMs = Math.round((parseInt(slider.value) / 1000) * durMs);
    pyBridge.seekTo(posMs);
});

function submitNewSong() {
    const path = document.getElementById("modal-path").value.trim();
    if (!path) {
        showToast("Нажми «Выбрать файл»", true);
        return;
    }
    pyBridge.addSongFull(
        document.getElementById("modal-title").value,
        document.getElementById("modal-artist").value,
        path,
        document.getElementById("modal-lyrics").value,
        document.getElementById("modal-cover").value.trim()
    );
    toggleAddModal();
}
