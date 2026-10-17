/* Набор line-иконок (стиль Feather, SVG stroke=currentColor — наследует цвет
   кнопки) для замены текстовых подписей на кнопках ("Инстр.", "Удал." и т.д.).
   Подсказка по наведению — через title у самой кнопки. */
const ICONS = {
    edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    removeFromList: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="8" y1="12" x2="16" y2="12"/></svg>',
    music: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
    scissors: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>',
    playlistAdd: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h12"/><path d="M3 12h9"/><path d="M3 18h6"/><path d="M15 17h6"/><path d="M18 14v6"/></svg>',
};

let pyBridge = null;
let isPlaying = false;
let currentLoopMode = "sequence";
let librarySongs = [];
let playlists = [];
let selectedSongId = null;
let currentPlayingSongId = null;
let activeSongPlaylistIds = [];
const MAX_PLAYLISTS_PER_SONG = 5;

var driveLoggedIn = false;

document.addEventListener("DOMContentLoaded", function() {
    var savedVideo = localStorage.getItem("blossom_video_bg");
    setVideoSource(savedVideo || "bg.webm");
    var sortSelect = document.getElementById("library-sort");
    if (sortSelect) {
        sortSelect.value = localStorage.getItem("blossom_library_sort") || "title_asc";
    }
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
    pyBridge.songChanged.connect(function(songId, title, artist, cover, lyrics, video, playlists, has_prev, has_next, has_lyrics, synced_lyrics) {
        document.getElementById("title").innerText = title;
        document.getElementById("artist").innerText = artist;
        currentPlainLyrics = lyrics;
        document.getElementById("cover").src = resolveCoverSrc(cover);
        const bp = document.getElementById("btn-prev");
        const bn = document.getElementById("btn-next");
        if (bp) bp.disabled = !has_prev;
        if (bn) bn.disabled = !has_next;
        const hasSong = !!songId;
        setPlaybackControlsEnabled(hasSong);
        setLyricsPanelAvailable(!!has_lyrics);
        setKaraokeLyrics(synced_lyrics || "");
        if (!hasSong) {
            isPlaying = false;
            setPlayIcon(false);
        }
        if (video && video.trim() !== "") {
            setVideoSource(video.trim());
        } else {
            var custom = localStorage.getItem("blossom_video_bg");
            setVideoSource(custom || "bg.webm");
        }
        currentPlayingSongId = songId || null;
        refreshActivePlaylistHighlight();
    });

    if (pyBridge.syncedLyricsReady) {
        pyBridge.syncedLyricsReady.connect(function(songId, lrc) {
            if (songId === currentPlayingSongId) {
                setKaraokeLyrics(lrc || "");
            }
        });
    }

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
            refreshActivePlaylistHighlight();
        });
    }

    if (pyBridge.playlistSongsReady) {
        pyBridge.playlistSongsReady.connect(function(playlistId, raw) {
            var currentId = parseInt(document.getElementById("pv-playlist-id").value);
            if (playlistId === currentId) {
                _renderPlaylistViewSongs(raw, playlistId);
            }
        });
    }

    if (pyBridge.playlistsForSongReady) {
        pyBridge.playlistsForSongReady.connect(function(songId, raw) {
            var modalSongId = parseInt(document.getElementById("pl-modal-song-id").value);
            if (songId === modalSongId) {
                _renderPlModalList(raw);
            }
            if (songId === currentPlayingSongId) {
                var data = [];
                try { data = typeof raw === "string" ? JSON.parse(raw) : raw; } catch (e) {}
                activeSongPlaylistIds = data.filter(function(p) { return p.has_song; }).map(function(p) { return p.id; });
                _applyPlaylistHighlight();
            }
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
            showBusyOverlay("import", "Скачиваю трек со Spotify…");
        });
    }

    if (pyBridge.importFinished) {
        pyBridge.importFinished.connect(function(title) {
            setImportStatus("Готово: " + title, false, true);
            setImportLock(false);
            hideBusyOverlay("import");
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.importFailed) {
        pyBridge.importFailed.connect(function(stage, code, message) {
            setImportStatus("[" + stage + ":" + code + "] " + message, true);
            setImportLock(false);
            hideBusyOverlay("import");
        });
    }

    if (pyBridge.importProgress) {
        pyBridge.importProgress.connect(function(msg) {
            setImportStatus(msg, false);
            updateBusyOverlay(msg);
        });
    }

    if (pyBridge.spotifyAutoProgress) {
        pyBridge.spotifyAutoProgress.connect(function(msg) {
            // Намеренно без showBusyOverlay: у этого импорта своя модалка со
            // статусом/логом и рабочей кнопкой "Остановить" — полноэкранный
            // busy-overlay (z-index выше модалки) лежал поверх неё и физически
            // перекрывал клик по "Остановить", так что он не работал.
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

    if (pyBridge.youtubeImportStarted) {
        pyBridge.youtubeImportStarted.connect(function() {
            setYoutubeImportStatus("Скачивание… подожди 1–3 мин", false);
            setYoutubeImportLock(true);
            showBusyOverlay("youtubeImport", "Скачиваю трек с YouTube…");
        });
    }

    if (pyBridge.youtubeImportFinished) {
        pyBridge.youtubeImportFinished.connect(function(title) {
            setYoutubeImportStatus("Готово: " + title, false, true);
            setYoutubeImportLock(false);
            hideBusyOverlay("youtubeImport");
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.youtubeImportFailed) {
        pyBridge.youtubeImportFailed.connect(function(stage, code, message) {
            setYoutubeImportStatus("[" + stage + ":" + code + "] " + message, true);
            setYoutubeImportLock(false);
            hideBusyOverlay("youtubeImport");
        });
    }

    if (pyBridge.youtubeImportProgress) {
        pyBridge.youtubeImportProgress.connect(function(msg) {
            setYoutubeImportStatus(msg, false);
            updateBusyOverlay(msg);
        });
    }

    if (pyBridge.artistImportProgress) {
        pyBridge.artistImportProgress.connect(function(msg) {
            // Без showBusyOverlay — та же причина, что у spotifyAuto выше:
            // у этой модалки своя кнопка "Остановить", оверлей её перекрывал.
            appendArtistImportLog(msg);
            setArtistImportStatus(msg, false);
        });
    }

    if (pyBridge.artistImportFinished) {
        pyBridge.artistImportFinished.connect(function(msg) {
            appendArtistImportLog(msg);
            setArtistImportStatus(msg, false, true);
            setArtistImportLock(false);
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.artistImportFailed) {
        pyBridge.artistImportFailed.connect(function(msg) {
            appendArtistImportLog(msg);
            setArtistImportStatus(msg, true);
            setArtistImportLock(false);
        });
    }

    if (pyBridge.youtubeChannelProgress) {
        pyBridge.youtubeChannelProgress.connect(function(msg) {
            // Без showBusyOverlay — та же причина: своя кнопка "Остановить",
            // оверлей её перекрывал.
            appendYoutubeChannelLog(msg);
            setYoutubeChannelStatus(msg, false);
        });
    }

    if (pyBridge.youtubeChannelFinished) {
        pyBridge.youtubeChannelFinished.connect(function(msg) {
            appendYoutubeChannelLog(msg);
            setYoutubeChannelStatus(msg, false, true);
            setYoutubeChannelLock(false);
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.youtubeChannelFailed) {
        pyBridge.youtubeChannelFailed.connect(function(msg) {
            appendYoutubeChannelLog(msg);
            setYoutubeChannelStatus(msg, true);
            setYoutubeChannelLock(false);
        });
    }

    if (pyBridge.instrumentalStarted) {
        pyBridge.instrumentalStarted.connect(function() {
            showToast("Ищу инструментал на YouTube…", false);
            showBusyOverlay("instrumental", "Ищу инструментал на YouTube…");
        });
    }

    if (pyBridge.instrumentalProgress) {
        pyBridge.instrumentalProgress.connect(function(msg) {
            showToast(msg, false);
            updateBusyOverlay(msg);
        });
    }

    if (pyBridge.instrumentalFound) {
        pyBridge.instrumentalFound.connect(function(json) {
            _unlockInstrumentalButtons();
            hideBusyOverlay("instrumental");
            openInstrumentalConfirm(json);
        });
    }

    if (pyBridge.instrumentalFinished) {
        pyBridge.instrumentalFinished.connect(function(title) {
            closeInstrumentalConfirm();
            showToast("Инструментал добавлен в «Инструменталы»: " + title, false);
            hideBusyOverlay("instrumental");
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.instrumentalFailed) {
        pyBridge.instrumentalFailed.connect(function(msg) {
            _unlockInstrumentalButtons();
            closeInstrumentalConfirm();
            showToast(msg, true);
            hideBusyOverlay("instrumental");
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.duplicatesScanProgress) {
        pyBridge.duplicatesScanProgress.connect(function(msg) {
            setDuplicatesStatus(msg, false);
            showBusyOverlay("duplicatesScan", msg);
        });
    }

    if (pyBridge.duplicatesScanFinished) {
        pyBridge.duplicatesScanFinished.connect(function(json) {
            setDuplicatesLock(false);
            hideBusyOverlay("duplicatesScan");
            var groups = [];
            try { groups = JSON.parse(json); } catch (e) { groups = []; }
            setDuplicatesStatus("Найдено групп дублей: " + groups.length, false, true);
            renderDuplicateGroups(groups);
        });
    }

    if (pyBridge.duplicatesScanFailed) {
        pyBridge.duplicatesScanFailed.connect(function(msg) {
            setDuplicatesStatus(msg, true);
            setDuplicatesLock(false);
            hideBusyOverlay("duplicatesScan");
        });
    }

    if (pyBridge.shazamStarted) {
        pyBridge.shazamStarted.connect(function() {
            setShazamLock(true);
            showBusyOverlay("shazam", "Распознаю трек…");
        });
    }

    if (pyBridge.shazamProgress) {
        pyBridge.shazamProgress.connect(function(msg) {
            setShazamStatus(msg, false);
            updateBusyOverlay(msg);
        });
    }

    if (pyBridge.shazamFinished) {
        pyBridge.shazamFinished.connect(function(title) {
            _clearShazamCountdown();
            setShazamStatus("Готово: " + title, false, true);
            setShazamLock(false);
            hideBusyOverlay("shazam");
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.shazamFailed) {
        pyBridge.shazamFailed.connect(function(msg) {
            _clearShazamCountdown();
            setShazamStatus(msg, true);
            setShazamLock(false);
            hideBusyOverlay("shazam");
        });
    }

    if (pyBridge.ocrFinished) {
        pyBridge.ocrFinished.connect(function(lines) {
            document.getElementById("btn-ocr-run").disabled = false;
            setOcrStatus("Готово. Выбери строку, которую скачать.", false, true);
            hideBusyOverlay("ocr");
            renderOcrResults(lines || []);
        });
    }

    if (pyBridge.ocrFailed) {
        pyBridge.ocrFailed.connect(function(msg) {
            document.getElementById("btn-ocr-run").disabled = false;
            setOcrStatus(msg, true);
            hideBusyOverlay("ocr");
        });
    }

    if (pyBridge.textSearchStarted) {
        pyBridge.textSearchStarted.connect(function() {
            showToast("Ищу на YouTube…", false);
            showBusyOverlay("textSearch", "Ищу на YouTube…");
        });
    }

    if (pyBridge.textSearchProgress) {
        pyBridge.textSearchProgress.connect(function(msg) {
            showToast(msg, false);
            updateBusyOverlay(msg);
        });
    }

    if (pyBridge.textSearchFinished) {
        pyBridge.textSearchFinished.connect(function(title) {
            showToast("Добавлено: " + title, false);
            hideBusyOverlay("textSearch");
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.textSearchFailed) {
        pyBridge.textSearchFailed.connect(function(msg) {
            showToast(msg, true);
            hideBusyOverlay("textSearch");
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

    if (pyBridge.lyricsPreviewReady) {
        pyBridge.lyricsPreviewReady.connect(function(json) {
            var data = {};
            try { data = typeof json === "string" ? JSON.parse(json) : json; } catch (e) {}
            modalLyricsAutoResult = data.lyrics || "";
            var resultEl = document.getElementById("modal-lyrics-auto-result");
            if (resultEl) resultEl.value = modalLyricsAutoResult;
            if (data.status === "instrumental") {
                setModalLyricsAutoStatus("Похоже, это инструментал — слов нет", false, true);
            } else {
                var extra = data.identified_title ?
                    (" (распознано как " + data.identified_artist + " — " + data.identified_title + ")") : "";
                setModalLyricsAutoStatus("Текст найден" + extra, false, true);
            }
        });
    }

    if (pyBridge.lyricsPreviewFailed) {
        pyBridge.lyricsPreviewFailed.connect(function(msg) {
            setModalLyricsAutoStatus(msg, true);
        });
    }

    if (pyBridge.lyricsBulkStarted) {
        pyBridge.lyricsBulkStarted.connect(function() {
            document.getElementById("lyrics-bulk-log").innerText = "";
            appendLyricsBulkLog("Начинаю поиск текстов…");
            setLyricsBulkLock(true);
        });
    }

    if (pyBridge.lyricsBulkProgress) {
        pyBridge.lyricsBulkProgress.connect(function(msg) {
            appendLyricsBulkLog(msg);
            setLyricsBulkStatus(msg, false);
        });
    }

    if (pyBridge.lyricsBulkFinished) {
        pyBridge.lyricsBulkFinished.connect(function(msg) {
            appendLyricsBulkLog(msg);
            setLyricsBulkStatus(msg, false, true);
            setLyricsBulkLock(false);
            if (pyBridge.getLibraryJson) pyBridge.getLibraryJson();
        });
    }

    if (pyBridge.lyricsBulkFailed) {
        pyBridge.lyricsBulkFailed.connect(function(msg) {
            appendLyricsBulkLog(msg);
            setLyricsBulkStatus(msg, true);
            setLyricsBulkLock(false);
        });
    }
}

function resolveCoverSrc(cover) {
    if (!cover) return "../assets/default_cover.png";
    if (cover.startsWith("file:///")) return cover;
    return cover;
}

/* === Единый оверлей "идёт долгая операция" (скачивание/распознавание/поиск дублей) ===
   Несколько операций разных типов теоретически могут идти параллельно — поэтому
   набор активных имён, а не просто счётчик: оверлей прячется только когда все ушли. */
var _busyOps = new Set();

function showBusyOverlay(opName, text) {
    _busyOps.add(opName);
    var el = document.getElementById("busy-overlay");
    if (el) el.classList.remove("hidden");
    updateBusyOverlay(text);
}

function updateBusyOverlay(text) {
    var t = document.getElementById("busy-overlay-text");
    if (t) t.textContent = text || "";
}

function hideBusyOverlay(opName) {
    _busyOps.delete(opName);
    if (_busyOps.size === 0) {
        var el = document.getElementById("busy-overlay");
        if (el) el.classList.add("hidden");
    }
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
        const parts = base.split(/\s*-\s*/);
        const t = document.getElementById("modal-title");
        const a = document.getElementById("modal-artist");
        if (parts.length >= 2) {
            if (a && !a.value.trim()) a.value = parts[0].trim();
            if (t && !t.value.trim()) t.value = parts.slice(1).join(" - ").trim();
        } else if (t && !t.value.trim()) {
            t.value = base;
        }
    } else if (kind === "cover" || kind === "cover_local" || kind === "cover_youtube") {
        const id = kind === "cover" ? "spotify-cover" : kind === "cover_youtube" ? "youtube-cover" : "modal-cover";
        document.getElementById(id).value = path;
        if (kind === "cover_local") {
            const preview = document.getElementById("modal-cover-preview");
            if (preview) {
                preview.src = "file:///" + path.replace(/\\/g, "/");
                preview.classList.remove("hidden");
            }
        }
    } else if (kind === "cover_edit") {
        document.getElementById("edit-cover-path").value = path;
        document.getElementById("edit-cover-preview").src = "file:///" + path.replace(/\\/g, "/");
    } else if (kind === "video_bg") {
        document.getElementById("settings-video-path").value = path;
    } else if (kind === "ocr_image") {
        document.getElementById("ocr-image-path").value = path;
    } else if (kind === "shazam_audio") {
        setShazamLock(true);
        setShazamStatus("Распознаю файл…");
        pyBridge.identifyFromAudioFile(path);
    }
}

function pickFile(kind) {
    if (pyBridge && pyBridge.pickFile) pyBridge.pickFile(kind);
}

function getLibrarySortMode() {
    var sel = document.getElementById("library-sort");
    return (sel && sel.value) || localStorage.getItem("blossom_library_sort") || "title_asc";
}

function sortLibrarySongs(songs, mode) {
    var collator = function(a, b) { return String(a || "").localeCompare(String(b || ""), "ru"); };
    var sorted = songs.slice();
    switch (mode) {
        case "title_desc":
            sorted.sort(function(a, b) { return collator(b.title_raw || b.title, a.title_raw || a.title); });
            break;
        case "artist_asc":
            sorted.sort(function(a, b) { return collator(a.artist_raw || a.artist, b.artist_raw || b.artist) || collator(a.title_raw || a.title, b.title_raw || b.title); });
            break;
        case "added_desc":
            sorted.sort(function(a, b) { return (b.added_at || 0) - (a.added_at || 0); });
            break;
        case "added_asc":
            sorted.sort(function(a, b) { return (a.added_at || 0) - (b.added_at || 0); });
            break;
        case "title_asc":
        default:
            sorted.sort(function(a, b) { return collator(a.title_raw || a.title, b.title_raw || b.title); });
            break;
    }
    return sorted;
}

function onLibrarySortChange() {
    var sel = document.getElementById("library-sort");
    if (sel) localStorage.setItem("blossom_library_sort", sel.value);
    renderLibrary(librarySongs);
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
    const sortedSongs = sortLibrarySongs(librarySongs, getLibrarySortMode());
    if (!librarySongs.length) {
        list.innerHTML = "<p style='font-size:12px;color:#9a86a4;padding:8px'>Пока нет треков</p>";
        return;
    }
    sortedSongs.forEach(function(s) {
        const row = document.createElement("div");
        row.className = "song-item song-row-clickable";
        const cover = s.cover || "../assets/default_cover.png";
        row.innerHTML =
            "<img src='" + cover + "' alt=''>" +
            "<div class='song-item-info'>" +
            "<div class='song-item-title'>" + escapeHtml(s.title_raw || s.title) + "</div>" +
            "<div class='song-item-artist'>" + escapeHtml(s.artist_raw || s.artist) + "</div>" +
            (s.playlists && s.playlists.length ?
                "<div class='song-item-playlists'>&#9834; " + escapeHtml(s.playlists.join(", ")) + "</div>" : "") +
            "</div>" +
            "<div class='song-item-actions'>" +
            "<button type='button' class='icon-btn' data-playlist='" + s.id + "' title='Добавить в плейлист'>" + ICONS.playlistAdd + "</button>" +
            "<button type='button' class='icon-btn' data-edit='" + s.id + "' title='Изменить название, автора, обложку, текст'>" + ICONS.edit + "</button>" +
            "<button type='button' class='icon-btn' data-instr='" + s.id + "' title='Найти инструментал на YouTube'>" + ICONS.music + "</button>" +
            "<button type='button' class='icon-btn' data-trim='" + s.id + "' title='Обрезать начало/конец'>" + ICONS.scissors + "</button>" +
            "<button type='button' class='icon-btn icon-btn-danger' data-del='" + s.id + "' title='Удалить трек'>" + ICONS.trash + "</button>" +
            "</div>";
        row.title = "Нажми, чтобы включить";
        row.onclick = function() {
            selectedSongId = s.id;
            pyBridge.playSongById(s.id);
            isPlaying = true;
            setPlayIcon(true);
        };
        list.appendChild(row);
    });
    list.querySelectorAll("[data-playlist]").forEach(function(btn) {
        btn.onclick = function(e) { e.stopPropagation(); openPlaylistModal(parseInt(btn.getAttribute("data-playlist"))); };
    });
    list.querySelectorAll("[data-edit]").forEach(function(btn) {
        btn.onclick = function(e) { e.stopPropagation(); openEditModal(parseInt(btn.getAttribute("data-edit"))); };
    });
    list.querySelectorAll("[data-del]").forEach(function(btn) {
        btn.onclick = function(e) {
            e.stopPropagation();
            if (confirm("Удалить этот трек?")) pyBridge.deleteSongById(parseInt(btn.getAttribute("data-del")));
        };
    });
    list.querySelectorAll("[data-instr]").forEach(function(btn) {
        btn.onclick = function(e) {
            e.stopPropagation();
            btn.disabled = true;
            pyBridge.findInstrumental(parseInt(btn.getAttribute("data-instr")));
        };
    });
    list.querySelectorAll("[data-trim]").forEach(function(btn) {
        btn.onclick = function(e) { e.stopPropagation(); openTrimModal(parseInt(btn.getAttribute("data-trim"))); };
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
        row.setAttribute("data-plid", p.id);
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
    _applyPlaylistHighlight();
}

function _applyPlaylistHighlight() {
    var list = document.getElementById("playlist-list");
    if (!list) return;
    list.querySelectorAll(".playlist-item").forEach(function(row) {
        var id = parseInt(row.getAttribute("data-plid"));
        row.classList.toggle("playlist-item-active", activeSongPlaylistIds.indexOf(id) !== -1);
    });
}

function refreshActivePlaylistHighlight() {
    if (pyBridge && pyBridge.requestPlaylistsForSong && currentPlayingSongId) {
        pyBridge.requestPlaylistsForSong(currentPlayingSongId);
    } else {
        activeSongPlaylistIds = [];
        _applyPlaylistHighlight();
    }
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

function switchLibraryTab(tab) {
    var panes = { songs: "library-tab-songs", playlists: "library-tab-playlists" };
    var btns = { songs: "lib-tab-btn-songs", playlists: "lib-tab-btn-playlists" };
    Object.keys(panes).forEach(function(key) {
        var pane = document.getElementById(panes[key]);
        var btn = document.getElementById(btns[key]);
        if (pane) pane.classList.toggle("hidden", key !== tab);
        if (btn) btn.classList.toggle("active", key === tab);
    });
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

function deleteEditLyrics() {
    document.getElementById("edit-lyrics").value = "";
    saveEditSong();
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

function setPlaybackControlsEnabled(enabled) {
    ["btn-play", "btn-stop", "btn-shuffle", "btn-loop"].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.disabled = !enabled;
    });
}

/* === Караоке: подсветка текущей строки текста в такт воспроизведению === */
var currentPlainLyrics = "";
var currentSyncedLines = [];   // [{time: ms, text: str}, ...]
var karaokeModeOn = false;

function parseLrc(lrcText) {
    if (!lrcText) return [];
    var lines = [];
    var re = /^\[(\d+):(\d+(?:\.\d+)?)\](.*)$/;
    lrcText.split("\n").forEach(function(raw) {
        var m = re.exec(raw);
        if (!m) return;
        var ms = (parseInt(m[1], 10) * 60 + parseFloat(m[2])) * 1000;
        lines.push({ time: ms, text: m[3].trim() });
    });
    lines.sort(function(a, b) { return a.time - b.time; });
    return lines;
}

function setKaraokeLyrics(lrcText) {
    currentSyncedLines = parseLrc(lrcText);
    var btn = document.getElementById("btn-karaoke-panel");
    var available = currentSyncedLines.length > 0;
    if (btn) {
        btn.disabled = !available;
        btn.title = available ? "Подсветка текста в такт песне" : "Для этой песни нет текста с таймкодами";
    }
    if (!available && karaokeModeOn) {
        karaokeModeOn = false;
    }
    renderLyricsBox();
}

function toggleKaraokeMode() {
    if (currentSyncedLines.length === 0) return;
    karaokeModeOn = !karaokeModeOn;
    var btn = document.getElementById("btn-karaoke-panel");
    if (btn) btn.classList.toggle("btn-active", karaokeModeOn);
    var panel = document.getElementById("side-panel");
    if (karaokeModeOn && panel && panel.classList.contains("hidden")) {
        panel.classList.remove("hidden");
    }
    renderLyricsBox();
}

function renderLyricsBox() {
    var box = document.getElementById("lyrics");
    if (!box) return;
    if (karaokeModeOn && currentSyncedLines.length > 0) {
        box.innerHTML = currentSyncedLines.map(function(line, i) {
            return '<div class="karaoke-line" data-index="' + i + '">' + (escapeHtml(line.text) || "&nbsp;") + "</div>";
        }).join("");
    } else {
        box.innerText = currentPlainLyrics;
    }
}

function updateKaraokeHighlight(posMs) {
    if (!karaokeModeOn || currentSyncedLines.length === 0) return;
    var active = -1;
    for (var i = 0; i < currentSyncedLines.length; i++) {
        if (currentSyncedLines[i].time <= posMs) active = i; else break;
    }
    var box = document.getElementById("lyrics");
    if (!box) return;
    var nodes = box.querySelectorAll(".karaoke-line");
    nodes.forEach(function(node, i) {
        if (i === active) {
            if (!node.classList.contains("karaoke-active")) {
                node.classList.add("karaoke-active");
                node.scrollIntoView({ block: "center", behavior: "smooth" });
            }
        } else {
            node.classList.remove("karaoke-active");
        }
    });
}

function setLyricsPanelAvailable(hasLyrics) {
    var btn = document.getElementById("btn-lyrics-panel");
    if (btn) {
        btn.disabled = !hasLyrics;
        btn.title = hasLyrics ? "Показать текст и фон" : "У этого трека пока нет текста";
    }
    if (!hasLyrics) {
        // Если панель была открыта у предыдущего трека — у нового трека текста
        // нет, оставлять открытую панель с чужим текстом/плейсхолдером не нужно.
        var panel = document.getElementById("side-panel");
        if (panel && !panel.classList.contains("hidden")) panel.classList.add("hidden");
    }
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

var modalLyricsTab = "manual";
var modalLyricsAutoResult = "";

function openLocalAdd() {
    document.getElementById("add-menu").classList.add("hidden");
    document.getElementById("modal-path").value = "";
    document.getElementById("modal-title").value = "";
    document.getElementById("modal-artist").value = "";
    document.getElementById("modal-lyrics").value = "";
    document.getElementById("modal-cover").value = "";
    var preview = document.getElementById("modal-cover-preview");
    if (preview) { preview.src = ""; preview.classList.add("hidden"); }
    document.getElementById("modal-lyrics-auto-result").value = "";
    modalLyricsAutoResult = "";
    setModalLyricsAutoStatus("");
    switchModalLyricsTab("manual");
    toggleAddModal();
}

function switchModalLyricsTab(tab) {
    modalLyricsTab = tab;
    document.getElementById("modal-lyrics-tab-manual").classList.toggle("active", tab === "manual");
    document.getElementById("modal-lyrics-tab-auto").classList.toggle("active", tab === "auto");
    document.getElementById("modal-lyrics").classList.toggle("hidden", tab !== "manual");
    document.getElementById("modal-lyrics-auto-pane").classList.toggle("hidden", tab !== "auto");
}

function setModalLyricsAutoStatus(text, isError, isOk) {
    var el = document.getElementById("modal-lyrics-auto-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

function searchLocalAddLyrics() {
    if (!pyBridge || !pyBridge.searchLyricsPreview) return;
    var title = document.getElementById("modal-title").value.trim();
    if (!title) {
        setModalLyricsAutoStatus("Сначала укажи название песни", true);
        return;
    }
    var artist = document.getElementById("modal-artist").value.trim() || "Unknown Artist";
    var filepath = document.getElementById("modal-path").value.trim();
    document.getElementById("modal-lyrics-auto-result").value = "";
    modalLyricsAutoResult = "";
    setModalLyricsAutoStatus("Ищу текст…", false);
    pyBridge.searchLyricsPreview(title, artist, filepath);
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

/* === YouTube Import === */

function setYoutubeImportLock(locked) {
    var btn = document.getElementById("btn-youtube-import");
    if (btn) btn.disabled = locked;
    var ids = ["youtube-url", "youtube-lyrics", "youtube-cover"];
    ids.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.readOnly = locked;
    });
}

function setYoutubeImportStatus(text, isError, isOk) {
    const el = document.getElementById("youtube-import-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

function openYoutubeModal() {
    document.getElementById("add-menu").classList.add("hidden");
    document.getElementById("youtube-url").value = "";
    document.getElementById("youtube-lyrics").value = "";
    document.getElementById("youtube-cover").value = "";
    document.getElementById("youtube-modal").style.display = "flex";
    setYoutubeImportStatus("");
}

function closeYoutubeModal() {
    document.getElementById("youtube-modal").style.display = "none";
}

function submitYoutubeImport() {
    const url = document.getElementById("youtube-url").value.trim();
    const isYoutube = /(youtube\.com\/(watch\?v=|shorts\/|embed\/)|youtu\.be\/)/i.test(url);
    if (!url || !isYoutube) {
        setYoutubeImportStatus("Нужна ссылка на видео YouTube", true);
        return;
    }
    pyBridge.importFromYoutube(
        url,
        document.getElementById("youtube-lyrics").value,
        document.getElementById("youtube-cover").value.trim(),
        document.getElementById("youtube-upload-drive").checked
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

/* === Artist discography (Spotify) === */

var artistImportRunning = false;

function openArtistModal() {
    document.getElementById("add-menu").classList.add("hidden");
    document.getElementById("artist-query").value = "";
    document.getElementById("artist-import-modal").style.display = "flex";
    if (!artistImportRunning) {
        document.getElementById("artist-import-log").innerText = "";
        setArtistImportStatus("");
    }
}

function closeArtistModal() {
    document.getElementById("artist-import-modal").style.display = "none";
}

function startArtistImport() {
    if (!pyBridge || !pyBridge.importArtistFromSpotify) return;
    if (artistImportRunning) return;
    const query = document.getElementById("artist-query").value.trim();
    if (!query) {
        setArtistImportStatus("Вставь ссылку на артиста или имя", true);
        return;
    }
    document.getElementById("artist-import-log").innerText = "";
    appendArtistImportLog("Начинаю поиск и скачивание…");
    setArtistImportLock(true);
    pyBridge.importArtistFromSpotify(query);
}

function stopArtistImport() {
    if (pyBridge && pyBridge.stopArtistImport) pyBridge.stopArtistImport();
}

function setArtistImportLock(locked) {
    artistImportRunning = locked;
    var startBtn = document.getElementById("btn-artist-import-start");
    var stopBtn = document.getElementById("btn-artist-import-stop");
    if (startBtn) startBtn.disabled = locked;
    if (stopBtn) stopBtn.disabled = !locked;
}

function appendArtistImportLog(msg) {
    var log = document.getElementById("artist-import-log");
    if (!log || !msg) return;
    var line = document.createElement("div");
    line.innerText = msg;
    log.appendChild(line);
    while (log.childNodes.length > 300) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
}

function setArtistImportStatus(text, isError, isOk) {
    var el = document.getElementById("artist-import-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

/* === YouTube channel/playlist bulk import === */

var youtubeChannelRunning = false;

function openYoutubeChannelModal() {
    document.getElementById("add-menu").classList.add("hidden");
    document.getElementById("youtube-channel-url").value = "";
    document.getElementById("youtube-channel-modal").style.display = "flex";
    if (!youtubeChannelRunning) {
        document.getElementById("youtube-channel-log").innerText = "";
        setYoutubeChannelStatus("");
    }
}

function closeYoutubeChannelModal() {
    document.getElementById("youtube-channel-modal").style.display = "none";
}

function startYoutubeChannelImport() {
    if (!pyBridge || !pyBridge.importYoutubeChannel) return;
    if (youtubeChannelRunning) return;
    const url = document.getElementById("youtube-channel-url").value.trim();
    if (!url || url.indexOf("youtu") === -1) {
        setYoutubeChannelStatus("Нужна ссылка на канал или плейлист YouTube", true);
        return;
    }
    document.getElementById("youtube-channel-log").innerText = "";
    appendYoutubeChannelLog("Читаю список видео…");
    setYoutubeChannelLock(true);
    pyBridge.importYoutubeChannel(url);
}

function stopYoutubeChannelImport() {
    if (pyBridge && pyBridge.stopYoutubeChannel) pyBridge.stopYoutubeChannel();
}

function setYoutubeChannelLock(locked) {
    youtubeChannelRunning = locked;
    var startBtn = document.getElementById("btn-youtube-channel-start");
    var stopBtn = document.getElementById("btn-youtube-channel-stop");
    if (startBtn) startBtn.disabled = locked;
    if (stopBtn) stopBtn.disabled = !locked;
}

function appendYoutubeChannelLog(msg) {
    var log = document.getElementById("youtube-channel-log");
    if (!log || !msg) return;
    var line = document.createElement("div");
    line.innerText = msg;
    log.appendChild(line);
    while (log.childNodes.length > 300) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
}

function setYoutubeChannelStatus(text, isError, isOk) {
    var el = document.getElementById("youtube-channel-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

/* === Shazam: identify a song by sound === */

function openShazamModal() {
    document.getElementById("add-menu").classList.add("hidden");
    setShazamStatus("");
    setShazamLock(false);
    document.getElementById("shazam-modal").style.display = "flex";
}

function closeShazamModal() {
    document.getElementById("shazam-modal").style.display = "none";
}

function setShazamStatus(text, isError, isOk) {
    var el = document.getElementById("shazam-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

function setShazamLock(locked) {
    var listenBtn = document.getElementById("btn-shazam-listen");
    var fileBtn = document.getElementById("btn-shazam-file");
    if (listenBtn) listenBtn.disabled = locked;
    if (fileBtn) fileBtn.disabled = locked;
}

let _shazamCountdownTimer = null;

function _clearShazamCountdown() {
    if (_shazamCountdownTimer) {
        clearInterval(_shazamCountdownTimer);
        _shazamCountdownTimer = null;
    }
}

function _runShazamCountdown(seconds, label) {
    _clearShazamCountdown();
    let remaining = seconds;
    setShazamStatus(label + ": осталось " + remaining + " сек…");
    _shazamCountdownTimer = setInterval(function() {
        remaining -= 1;
        if (remaining <= 0) {
            _clearShazamCountdown();
            setShazamStatus("Распознаю трек…");
            return;
        }
        setShazamStatus(label + ": осталось " + remaining + " сек…");
    }, 1000);
}

function startShazamListen() {
    if (!pyBridge || !pyBridge.startShazamListen) return;
    let seconds = Math.round(parseFloat(document.getElementById("shazam-seconds").value) || 8);
    seconds = Math.max(8, Math.min(30, seconds));
    document.getElementById("shazam-seconds").value = seconds;
    const sourceEl = document.getElementById("shazam-source");
    const source = (sourceEl && sourceEl.value) || "mic";
    setShazamLock(true);
    _runShazamCountdown(seconds, source === "loopback" ? "Слушаю звук компьютера" : "Слушаю микрофон");
    pyBridge.startShazamListen(seconds, source);
}

/* === OCR: recognize song name from an image === */

function openOcrModal() {
    document.getElementById("add-menu").classList.add("hidden");
    document.getElementById("ocr-image-path").value = "";
    document.getElementById("ocr-results").innerHTML = "";
    setOcrStatus("");
    document.getElementById("ocr-modal").style.display = "flex";
}

function closeOcrModal() {
    document.getElementById("ocr-modal").style.display = "none";
}

function setOcrStatus(text, isError, isOk) {
    var el = document.getElementById("ocr-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

function submitOcr() {
    const path = document.getElementById("ocr-image-path").value.trim();
    if (!path) {
        setOcrStatus("Сначала выбери картинку", true);
        return;
    }
    const lang = document.getElementById("ocr-lang").value;
    document.getElementById("ocr-results").innerHTML = "";
    setOcrStatus("Распознаю…");
    document.getElementById("btn-ocr-run").disabled = true;
    showBusyOverlay("ocr", "Распознаю текст на картинке…");
    pyBridge.recognizeImageText(path, lang);
}

function renderOcrResults(items) {
    var list = document.getElementById("ocr-results");
    list.innerHTML = "";
    if (!items.length) {
        list.innerHTML = "<p style='font-size:12px;color:#9a86a4'>Текст не распознан.</p>";
        return;
    }
    items.forEach(function(item) {
        // Поддержка и старого формата (просто строки), и нового ({text, is_line}).
        var text = (typeof item === "string") ? item : item.text;
        var isLine = (typeof item === "string") ? true : item.is_line;
        var row = document.createElement("div");
        row.className = "duplicate-row" + (isLine ? "" : " ocr-candidate-row");
        var span = document.createElement("span");
        span.innerText = text;
        var btn = document.createElement("button");
        btn.type = "button";
        btn.innerText = "Скачать";
        btn.onclick = function() {
            btn.disabled = true;
            pyBridge.downloadFromText(text);
        };
        row.appendChild(span);
        row.appendChild(btn);
        list.appendChild(row);
    });
}

/* === Инструментал: подтверждение перед скачиванием === */
var instrumentalFoundData = null;

function _unlockInstrumentalButtons() {
    document.querySelectorAll("[data-instr]").forEach(function(b) { b.disabled = false; });
}

function _formatDuration(seconds) {
    seconds = parseInt(seconds) || 0;
    var m = Math.floor(seconds / 60), s = seconds % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
}

function openInstrumentalConfirm(json) {
    try {
        instrumentalFoundData = typeof json === "string" ? JSON.parse(json) : json;
    } catch (e) {
        return;
    }
    var d = instrumentalFoundData;
    document.getElementById("instr-confirm-title").textContent = d.video_title || "";
    var meta = [];
    if (d.video_channel) meta.push(d.video_channel);
    if (d.video_duration) meta.push(_formatDuration(d.video_duration));
    document.getElementById("instr-confirm-meta").textContent = meta.join(" · ");
    document.getElementById("instrumental-confirm-modal").style.display = "flex";
}

function closeInstrumentalConfirm() {
    document.getElementById("instrumental-confirm-modal").style.display = "none";
    instrumentalFoundData = null;
}

function openInstrumentalOnYoutube() {
    if (instrumentalFoundData && instrumentalFoundData.video_url) {
        window.open(instrumentalFoundData.video_url, "_blank");
    }
}

function confirmInstrumentalDownload() {
    if (!instrumentalFoundData || !pyBridge || !pyBridge.downloadInstrumental) return;
    pyBridge.downloadInstrumental(instrumentalFoundData.song_id, instrumentalFoundData.video_url);
    showToast("Скачиваю инструментал…", false);
    closeInstrumentalConfirm();
}

/* === Trim start/end === */

function openTrimModal(songId) {
    document.getElementById("trim-song-id").value = songId;
    document.getElementById("trim-start").value = "0";
    document.getElementById("trim-end").value = "0";
    document.getElementById("trim-modal").style.display = "flex";
}

function closeTrimModal() {
    document.getElementById("trim-modal").style.display = "none";
}

function submitTrim() {
    const songId = parseInt(document.getElementById("trim-song-id").value);
    const start = parseFloat(document.getElementById("trim-start").value) || 0;
    const end = parseFloat(document.getElementById("trim-end").value) || 0;
    if (start <= 0 && end <= 0) {
        alert("Укажи сколько секунд обрезать с начала и/или с конца");
        return;
    }
    pyBridge.trimSongById(songId, start, end);
    closeTrimModal();
}

/* === Duplicate finder (by audio fingerprint) === */

var duplicatesScanRunning = false;
var lastDuplicateGroups = [];

function openDuplicatesModal() {
    document.getElementById("duplicates-modal").style.display = "flex";
}

function closeDuplicatesModal() {
    document.getElementById("duplicates-modal").style.display = "none";
}

function setDuplicatesStatus(text, isError, isOk) {
    var el = document.getElementById("duplicates-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
}

function setDuplicatesLock(locked) {
    duplicatesScanRunning = locked;
    var startBtn = document.getElementById("btn-duplicates-scan");
    var stopBtn = document.getElementById("btn-duplicates-stop");
    var autoBtn = document.getElementById("btn-duplicates-auto");
    if (startBtn) startBtn.disabled = locked;
    if (stopBtn) stopBtn.disabled = !locked;
    if (autoBtn) autoBtn.disabled = locked || !lastDuplicateGroups.length;
}

function startDuplicatesScan() {
    if (!pyBridge || !pyBridge.findDuplicates) return;
    if (duplicatesScanRunning) return;
    document.getElementById("duplicates-list").innerHTML = "";
    lastDuplicateGroups = [];
    // Кнопка "Удалить всё автоматически" появляется только ПОСЛЕ того, как поиск
    // нашёл дубли — до этого её не должно быть видно вообще, не только disabled.
    var autoBtn = document.getElementById("btn-duplicates-auto");
    if (autoBtn) autoBtn.classList.add("hidden");
    setDuplicatesStatus("Запускаю поиск…");
    setDuplicatesLock(true);
    pyBridge.findDuplicates();
}

function stopDuplicatesScan() {
    if (pyBridge && pyBridge.stopDuplicateScan) pyBridge.stopDuplicateScan();
}

/* Выполняет fn(item) по элементам items пачками по batchSize штук с паузой
   delayMs между пачками (а не всё сразу одним тугим циклом). Каждый вызов
   fn — это синхронный pyqtSlot (сетевой Drive-запрос + пересборка всей
   библиотеки на Python-стороне + перерисовка DOM), и без пауз между пачками
   десятки таких вызовов подряд забивали GUI-поток/QtWebChannel и роняли
   приложение — та же причина, что и у краша при массовом удалении текста. */
function runInBatches(items, batchSize, delayMs, fn, onDone) {
    var i = 0;
    function nextBatch() {
        items.slice(i, i + batchSize).forEach(fn);
        i += batchSize;
        if (i < items.length) {
            setTimeout(nextBatch, delayMs);
        } else if (onDone) {
            onDone();
        }
    }
    if (items.length) nextBatch();
    else if (onDone) onDone();
}

function autoResolveAllDuplicates() {
    if (!pyBridge || !lastDuplicateGroups.length) return;
    var totalGroups = 0;
    var idsToDelete = [];
    lastDuplicateGroups.forEach(function(group) {
        if (!group.songs || group.songs.length < 2) return;
        totalGroups += 1;
        var keepId = group.songs.reduce(function(best, s) {
            return (!best || (s.filesize || 0) > (best.filesize || 0)) ? s : best;
        }, null).id;
        group.songs.forEach(function(s) {
            if (s.id !== keepId) idsToDelete.push(s.id);
        });
    });
    if (!idsToDelete.length) return;
    if (!confirm(
        "Удалить " + idsToDelete.length + " лишних копий в " + totalGroups + " группах? " +
        "В каждой группе останется одна песня (с наибольшим размером файла)."
    )) return;
    runInBatches(idsToDelete, 10, 400, function(id) { pyBridge.deleteSongById(id); }, function() {
        document.getElementById("duplicates-list").innerHTML = "<p style='font-size:12px;color:#9a86a4'>Готово — лишние копии удалены.</p>";
        lastDuplicateGroups = [];
        var autoBtn = document.getElementById("btn-duplicates-auto");
        if (autoBtn) {
            autoBtn.disabled = true;
            autoBtn.classList.add("hidden");
        }
    });
}

function _formatFilesize(bytes) {
    if (!bytes) return "";
    var mb = bytes / (1024 * 1024);
    return mb >= 0.1 ? mb.toFixed(1) + " МБ" : Math.round(bytes / 1024) + " КБ";
}

function renderDuplicateGroups(groups) {
    var list = document.getElementById("duplicates-list");
    list.innerHTML = "";
    lastDuplicateGroups = groups || [];
    var autoBtn = document.getElementById("btn-duplicates-auto");
    if (autoBtn) {
        autoBtn.classList.toggle("hidden", !lastDuplicateGroups.length);
        autoBtn.disabled = duplicatesScanRunning || !lastDuplicateGroups.length;
    }
    if (!groups.length) {
        list.innerHTML = "<p style='font-size:12px;color:#9a86a4'>Дублей не найдено.</p>";
        return;
    }
    groups.forEach(function(group, gIndex) {
        var block = document.createElement("div");
        block.className = "duplicate-group";
        block.setAttribute("data-group", gIndex);
        // По умолчанию оставляем трек с наибольшим размером файла (вероятно лучшее качество).
        var keepId = group.songs.reduce(function(best, s) {
            return (!best || (s.filesize || 0) > (best.filesize || 0)) ? s : best;
        }, null).id;
        var kind = (group.songs[0] && group.songs[0].is_instrumental) ? "инструментала" : "трека";
        var html = "<div style='font-size:12px;color:#9a86a4;margin:6px 0 2px'>" +
            "Дубликаты одного " + kind + " (" + group.songs.length + ") — выберите, какой оставить:</div>";
        group.songs.forEach(function(s) {
            html += "<label class='duplicate-row' data-song-row='" + s.id + "'>" +
                "<span><input type='radio' name='dupkeep-" + gIndex + "' value='" + s.id + "'" +
                (s.id === keepId ? " checked" : "") + "> " +
                escapeHtml(s.artist_raw || s.artist) + " — " + escapeHtml(s.title_raw || s.title) +
                " <span style='color:#b3a1bd'>(" + _formatFilesize(s.filesize) + ")</span></span>" +
                "</label>";
        });
        html += "<button type='button' class='btn-dup-resolve' data-group-resolve='" + gIndex + "'>Удалить лишние</button>";
        block.innerHTML = html;
        list.appendChild(block);
    });
    list.querySelectorAll("[data-group-resolve]").forEach(function(btn) {
        btn.onclick = function() {
            var gIndex = parseInt(btn.getAttribute("data-group-resolve"));
            var group = groups[gIndex];
            var block = list.querySelector("[data-group='" + gIndex + "']");
            var checked = block.querySelector("input[name='dupkeep-" + gIndex + "']:checked");
            if (!checked) return;
            var keepId = parseInt(checked.value);
            var toDelete = group.songs.filter(function(s) { return s.id !== keepId; }).map(function(s) { return s.id; });
            if (!toDelete.length) return;
            if (!confirm("Удалить " + toDelete.length + " лишних копий, оставить одну?")) return;
            toDelete.forEach(function(id) { pyBridge.deleteSongById(id); });
            groups[gIndex] = { songs: [] };
            if (block) block.remove();
        };
    });
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
    if (pyBridge && pyBridge.requestPlaylistsForSong) {
        pyBridge.requestPlaylistsForSong(songId);
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
        cb.onchange = function() {
            plModalChecked[parseInt(cb.getAttribute("data-plid"))] = cb.checked;
            _applyPlModalLimit();
        };
    });
    _applyPlModalLimit();
}

function _applyPlModalLimit() {
    var checkedCount = Object.keys(plModalChecked).filter(function(id) { return plModalChecked[id]; }).length;
    var atLimit = checkedCount >= MAX_PLAYLISTS_PER_SONG;
    var hint = document.getElementById("pl-modal-limit-hint");
    if (hint) hint.classList.toggle("hidden", !atLimit);
    document.querySelectorAll("#pl-modal-list input[data-plid]").forEach(function(cb) {
        cb.disabled = atLimit && !cb.checked;
    });
}

function plModalCreateAndAdd() {
    var name = document.getElementById("pl-modal-new-name").value.trim();
    if (!name) { showToast("Введи название", true); return; }
    if (pyBridge) pyBridge.createPlaylist(name);
    document.getElementById("pl-modal-new-name").value = "";
    // createPlaylist выполняется синхронно на стороне Python раньше, чем JS успевает
    // послать следующий вызов — отдельный setTimeout-поллинг тут не нужен.
    var songId = parseInt(document.getElementById("pl-modal-song-id").value);
    if (pyBridge && pyBridge.requestPlaylistsForSong) {
        pyBridge.requestPlaylistsForSong(songId);
    }
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
    if (songId === currentPlayingSongId) refreshActivePlaylistHighlight();
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
    document.getElementById("playlist-list-view").classList.add("hidden");
    document.getElementById("playlist-detail-view").classList.remove("hidden");
    if (pyBridge && pyBridge.requestPlaylistSongs) {
        pyBridge.requestPlaylistSongs(playlistId);
    }
}

function backToPlaylists() {
    document.getElementById("playlist-detail-view").classList.add("hidden");
    document.getElementById("playlist-list-view").classList.remove("hidden");
    document.getElementById("pv-playlist-id").value = "";
    refreshActivePlaylistHighlight();
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
        row.className = "pv-song-row song-row-clickable";
        var cover = s.cover || "../assets/default_cover.png";
        row.innerHTML =
            "<img src='" + cover + "' alt=''>" +
            "<div class='pv-song-info'>" +
            "<div class='pv-song-title'>" + escapeHtml(s.title_raw || s.title) + "</div>" +
            "<div class='pv-song-artist'>" + escapeHtml(s.artist_raw || s.artist) + "</div>" +
            (s.other_playlists && s.other_playlists.length ?
                "<div class='song-item-playlists'>&#9834; также: " + escapeHtml(s.other_playlists.join(", ")) + "</div>" : "") +
            "</div>" +
            "<div class='pv-song-actions'>" +
            "<button type='button' class='icon-btn' data-pvedit='" + s.id + "' title='Изменить название, автора, обложку, текст'>" + ICONS.edit + "</button>" +
            "<button type='button' class='icon-btn' data-pvplaylist='" + s.id + "' title='Добавить в другой плейлист'>" + ICONS.playlistAdd + "</button>" +
            "<button type='button' class='icon-btn icon-btn-danger' data-pvremove='" + s.id + "' title='Убрать из этого плейлиста'>" + ICONS.removeFromList + "</button>" +
            "</div>";
        row.title = "Нажми, чтобы включить";
        row.onclick = function() {
            selectedSongId = s.id;
            pyBridge.playSongById(s.id);
            isPlaying = true;
            setPlayIcon(true);
        };
        listEl.appendChild(row);
    });
    listEl.querySelectorAll("[data-pvedit]").forEach(function(btn) {
        btn.onclick = function(e) { e.stopPropagation(); openEditModal(parseInt(btn.getAttribute("data-pvedit"))); };
    });
    listEl.querySelectorAll("[data-pvplaylist]").forEach(function(btn) {
        btn.onclick = function(e) { e.stopPropagation(); openPlaylistModal(parseInt(btn.getAttribute("data-pvplaylist"))); };
    });
    listEl.querySelectorAll("[data-pvremove]").forEach(function(btn) {
        btn.onclick = function(e) {
            e.stopPropagation();
            var songId = parseInt(btn.getAttribute("data-pvremove"));
            pyBridge.removeSongFromPlaylist(playlistId, songId);
            var row = btn.closest(".pv-song-row");
            if (row) row.remove();
            // Пустой плейлист сервер удаляет сам (см. _delete_if_empty в bridge.py) —
            // не остаёмся на странице уже несуществующего плейлиста.
            if (!listEl.children.length) backToPlaylists();
        };
    });
}

function playCurrentPlaylist() {
    var plId = parseInt(document.getElementById("pv-playlist-id").value);
    if (pyBridge && plId) { pyBridge.playPlaylist(plId); isPlaying = true; setPlayIcon(true); }
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
    switchSettingsTab("general");
    document.getElementById("settings-modal").style.display = "flex";
    refreshDriveStatus();
}

function closeSettingsModal() {
    // Всегда именно скрывает, а не отменяет: массовый поиск текста (если он
    // идёт) продолжает работать в фоне независимо от видимости окна.
    document.getElementById("settings-modal").style.display = "none";
}

function switchSettingsTab(tab) {
    var panes = { general: "settings-tab-general", lyrics: "settings-tab-lyrics" };
    var btns = { general: "settings-tab-btn-general", lyrics: "settings-tab-btn-lyrics" };
    Object.keys(panes).forEach(function(key) {
        var pane = document.getElementById(panes[key]);
        var btn = document.getElementById(btns[key]);
        if (pane) pane.classList.toggle("hidden", key !== tab);
        if (btn) btn.classList.toggle("active", key === tab);
    });
}

function syncFromDrive() {
    if (pyBridge && pyBridge.syncFromDrive) {
        pyBridge.syncFromDrive();
    }
}

/* === Массовый поиск текстов песен === */

var lyricsBulkRunning = false;

function startLyricsBulkSearch() {
    if (!pyBridge || !pyBridge.findMissingLyrics) return;
    if (lyricsBulkRunning) return;
    pyBridge.findMissingLyrics();
}

function startLyricsBulkRecheck() {
    if (!pyBridge || !pyBridge.recheckInstrumentalLyrics) return;
    if (lyricsBulkRunning) return;
    pyBridge.recheckInstrumentalLyrics();
}

function startClearAllLyrics() {
    if (!pyBridge || !pyBridge.clearAllLyrics) return;
    if (lyricsBulkRunning) return;
    if (!confirm("Удалить текст у ВСЕХ песен в библиотеке? Это можно отменить только повторным поиском.")) return;
    pyBridge.clearAllLyrics();
}

function stopLyricsBulkSearch() {
    if (pyBridge && pyBridge.stopFindMissingLyrics) pyBridge.stopFindMissingLyrics();
}

function setLyricsBulkLock(locked) {
    lyricsBulkRunning = locked;
    var startBtn = document.getElementById("btn-lyrics-bulk-start");
    var recheckBtn = document.getElementById("btn-lyrics-bulk-recheck");
    var clearAllBtn = document.getElementById("btn-lyrics-clear-all");
    var stopBtn = document.getElementById("btn-lyrics-bulk-stop");
    var applyBtn = document.getElementById("btn-settings-apply");
    var closeBtn = document.getElementById("btn-settings-close");
    if (startBtn) startBtn.disabled = locked;
    if (recheckBtn) recheckBtn.disabled = locked;
    if (clearAllBtn) clearAllBtn.disabled = locked;
    if (stopBtn) stopBtn.disabled = !locked;
    // Пока идёт поиск: "Применить" недоступен (чтобы не путать с настройками,
    // которые не относятся к поиску), а "Закрыть" становится "Скрыть" —
    // напоминание, что окно просто прячется, а не останавливает поиск.
    if (applyBtn) applyBtn.disabled = locked;
    if (closeBtn) closeBtn.innerText = locked ? "Скрыть" : "Закрыть";
}

function appendLyricsBulkLog(msg) {
    var log = document.getElementById("lyrics-bulk-log");
    if (!log || !msg) return;
    var line = document.createElement("div");
    line.innerText = msg;
    log.appendChild(line);
    while (log.childNodes.length > 300) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
}

function setLyricsBulkStatus(text, isError, isOk) {
    var el = document.getElementById("lyrics-bulk-status");
    if (!el) return;
    el.innerText = text || "";
    el.className = "import-status" + (isError ? " error" : isOk ? " ok" : "");
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
    updateKaraokeHighlight(pos);
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
    const lyrics = modalLyricsTab === "auto" ?
        modalLyricsAutoResult : document.getElementById("modal-lyrics").value;
    pyBridge.addSongFull(
        document.getElementById("modal-title").value,
        document.getElementById("modal-artist").value,
        path,
        lyrics,
        document.getElementById("modal-cover").value.trim()
    );
    toggleAddModal();
}
