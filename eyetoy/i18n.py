"""User-facing text in English and French.

Every string the user can see goes through :func:`t`, keyed by an identifier,
with both languages side by side so a missing translation shows up in review
(and in tests/test_i18n.py). English is the default and the fallback.

Messages built in worker threads are translated when they are produced, in the
language active at that moment. Log messages are not translated: the log is a
diagnostic file, kept in English.
"""

from __future__ import annotations

LANGUAGES = {"en": "English", "fr": "Français"}
DEFAULT_LANGUAGE = "en"

_language = DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else DEFAULT_LANGUAGE


def language() -> str:
    return _language


def t(key: str, **values: object) -> str:
    entry = STRINGS[key]
    text = entry.get(_language) or entry["en"]
    return text.format(**values) if values else text


STRINGS: dict[str, dict[str, str]] = {
    # -- main window --------------------------------------------------------
    "overlay.connecting": {"en": "Connecting...", "fr": "Connexion..."},
    "overlay.searching": {"en": "Searching...", "fr": "Recherche..."},
    "panel.stream": {"en": "STREAM", "fr": "FLUX"},
    "panel.zoom": {"en": "ZOOM", "fr": "ZOOM"},
    "panel.zoom_hint": {"en": "Scroll to zoom", "fr": "Molette pour zoomer"},
    "panel.reset_view": {"en": "Reset view  (0)", "fr": "Recadrer  (0)"},
    "panel.image": {"en": "IMAGE", "fr": "IMAGE"},
    "panel.driver": {"en": "Driver...", "fr": "Pilote..."},
    "control.brightness": {"en": "Brightness", "fr": "Luminosité"},
    "control.exposure": {"en": "Exposure", "fr": "Exposition"},
    "control.saturation": {"en": "Saturation", "fr": "Saturation"},
    "control.autogain": {"en": "Auto exposure", "fr": "Exposition automatique"},
    "control.mirror": {"en": "Mirror", "fr": "Miroir"},
    "control.smooth": {"en": "Smoothing", "fr": "Lissage"},
    "action.photo": {"en": "Photo  (Space)", "fr": "Photo  (Espace)"},
    "action.record": {"en": "Record  (R)", "fr": "Enregistrer  (R)"},
    "action.stop": {"en": "Stop  (R)", "fr": "Arrêter  (R)"},
    "action.open_captures": {"en": "Open captures folder",
                             "fr": "Ouvrir le dossier des captures"},
    "mode.qvga30": {"en": "320 x 240 - 30 fps", "fr": "320 x 240 - 30 i/s"},
    "mode.qvga15": {"en": "320 x 240 - 15 fps", "fr": "320 x 240 - 15 i/s"},
    "mode.vga": {"en": "640 x 480 - max", "fr": "640 x 480 - max"},
    "vcam.check": {"en": "Virtual camera", "fr": "Caméra virtuelle"},
    "vcam.install_button": {"en": "Install support",
                            "fr": "Installer le support"},
    "vcam.obs_needed": {
        "en": "OBS Studio provides the required virtual device. OBS does not "
              "need to be running afterwards.",
        "fr": "OBS Studio fournit le périphérique virtuel requis. OBS n'a pas "
              "besoin de tourner ensuite."},
    "driver.install_button": {"en": "Install driver",
                              "fr": "Installer le pilote"},

    # -- status block -------------------------------------------------------
    "status.up": {"en": "OK", "fr": "OK"},
    "status.down": {"en": "OFF", "fr": "HS"},
    "status.rate": {"en": "{width}x{height}  {fps:5.1f} fps",
                    "fr": "{width}x{height}  {fps:5.1f} i/s"},
    "status.frames": {"en": "{frames} frames  {dropped} dropped",
                      "fr": "{frames} trames  {dropped} perdues"},
    "status.iso": {"en": "{errors} iso err.", "fr": "{errors} err. iso"},
    "status.link": {"en": "alt {alt}, {size} B", "fr": "alt {alt}, {size} o"},
    "status.rec": {"en": "REC {minutes:02d}:{seconds:02d}  {frames} frames",
                   "fr": "REC {minutes:02d}:{seconds:02d}  {frames} trames"},

    # -- toasts -------------------------------------------------------------
    "toast.stop_recording_first": {"en": "stop recording first",
                                   "fr": "arrête l'enregistrement d'abord"},
    "toast.mode_changing": {"en": "switching mode...",
                            "fr": "changement de mode..."},
    "toast.vcam_visible": {
        "en": "the camera is now visible in Discord, OBS, Teams",
        "fr": "la caméra est visible dans Discord, OBS, Teams"},
    "toast.vcam_unavailable": {"en": "no virtual camera available",
                               "fr": "aucune caméra virtuelle disponible"},
    "toast.vcam_ready": {"en": "virtual camera ready",
                         "fr": "caméra virtuelle prête"},
    "toast.no_image": {"en": "no image to save",
                       "fr": "aucune image à enregistrer"},
    "toast.photo_saved": {"en": "photo: {name}", "fr": "photo : {name}"},
    "toast.photo_failed": {"en": "could not save the photo: {error}",
                           "fr": "photo impossible : {error}"},
    "toast.recorded": {
        "en": "{name} - {frames} frames, {fps:.1f} fps, {mb:.1f} MB",
        "fr": "{name} - {frames} trames, {fps:.1f} i/s, {mb:.1f} Mo"},
    "toast.not_connected": {"en": "camera not connected",
                            "fr": "caméra non connectée"},
    "toast.record_failed": {"en": "could not start recording: {error}",
                            "fr": "enregistrement impossible : {error}"},
    "toast.recording_stopped": {"en": "recording stopped",
                                "fr": "enregistrement arrêté"},
    "toast.folder_failed": {"en": "folder unavailable: {error}",
                            "fr": "dossier inaccessible : {error}"},
    "toast.captures_dir": {"en": "captures now go to {path}",
                           "fr": "les captures iront dans {path}"},
    "toast.settings_reset": {"en": "image settings restored",
                             "fr": "réglages d'image rétablis"},
    "toast.no_log": {"en": "no log file", "fr": "aucun journal"},
    "toast.driver_installed": {"en": "driver installed",
                               "fr": "pilote installé"},
    "toast.unexpected_error": {
        "en": "unexpected error: {error} (see the log)",
        "fr": "erreur inattendue : {error} (voir le journal)"},

    # -- menu ---------------------------------------------------------------
    "menu.settings": {"en": "Settings", "fr": "Paramètres"},
    "menu.language": {"en": "Language", "fr": "Langue"},
    "menu.captures_dir": {"en": "Captures folder...",
                          "fr": "Dossier des captures..."},
    "menu.captures_default": {"en": "Use the default captures folder",
                              "fr": "Dossier des captures par défaut"},
    "menu.open_captures": {"en": "Open captures folder",
                           "fr": "Ouvrir le dossier des captures"},
    "menu.reset_image": {"en": "Restore default image settings",
                         "fr": "Rétablir les réglages d'image"},
    "menu.driver": {"en": "Camera driver...", "fr": "Pilote de la caméra..."},
    "menu.help": {"en": "Help", "fr": "Aide"},
    "menu.open_log": {"en": "Open log file", "fr": "Ouvrir le journal"},
    "menu.about": {"en": "About EyeToy Studio",
                   "fr": "À propos d'EyeToy Studio"},
    "dialog.choose_captures": {"en": "Choose the captures folder",
                               "fr": "Choisir le dossier des captures"},
    "about.title": {"en": "About", "fr": "À propos"},
    "about.text": {
        "en": "EyeToy Studio {version}\n\nUser-space driver and viewer for "
              "the PlayStation 2 EyeToy camera.\n\nGPL-2.0. Bridge and sensor "
              "register tables ported from the Linux gspca driver.\n\n"
              "Captures: {captures}\nLog: {log}",
        "fr": "EyeToy Studio {version}\n\nPilote en espace utilisateur et "
              "visionneuse pour la caméra EyeToy de la PlayStation 2.\n\n"
              "GPL-2.0. Tables de registres du bridge et du capteur portées "
              "du pilote Linux gspca.\n\nCaptures : {captures}\n"
              "Journal : {log}"},

    # -- driver dialog ------------------------------------------------------
    "driver.title": {"en": "Camera driver", "fr": "Pilote de la caméra"},
    "driver.headline_missing": {
        "en": "Windows has not assigned a usable driver to the camera.",
        "fr": "Windows n'a attribué aucun pilote utilisable à la caméra."},
    "driver.headline": {
        "en": "Driver for the camera's video interface.",
        "fr": "Pilote de l'interface vidéo de la caméra."},
    "driver.intro": {
        "en": "The EyeToy is not a standard (UVC) webcam: Windows has no "
              "driver for it. One click is enough, once.",
        "fr": "L'EyeToy n'est pas une webcam standard (UVC) : Windows n'a pas "
              "de pilote pour elle. Un clic suffit, une seule fois."},
    "driver.what": {"en": "What the installation does:",
                    "fr": "Ce que fait l'installation :"},
    "driver.detail_bind": {
        "en": "Binds WinUSB to the camera's video interface (interface 0).",
        "fr": "Lie WinUSB à l'interface vidéo de la caméra (interface 0)."},
    "driver.detail_cert": {
        "en": "Windows requires a signed catalogue: it is generated and "
              "signed on the spot, and its certificate added to the machine's "
              "trust store, as Zadig does. Uninstalling removes the driver "
              "and this certificate.",
        "fr": "Windows exige un catalogue signé : il est généré et signé sur "
              "place, et son certificat ajouté au magasin de confiance de la "
              "machine, comme le fait Zadig. Désinstaller retire le pilote et "
              "ce certificat."},
    "driver.detail_mic": {
        "en": "The built-in microphone (interfaces 1 and 2) is not touched.",
        "fr": "Le microphone intégré (interfaces 1 et 2) n'est pas touché."},
    "driver.install": {"en": "Install driver", "fr": "Installer le pilote"},
    "driver.manual": {"en": "Manual method", "fr": "Méthode manuelle"},
    "driver.uninstall": {"en": "Uninstall", "fr": "Désinstaller"},
    "driver.close": {"en": "Close", "fr": "Fermer"},
    "driver.zadig_steps": {
        "en": "In the Zadig window:\n"
              "  1.  Options > List All Devices\n"
              "  2.  EyeToy USB camera Namtai (Interface 0)\n"
              "  3.  Target WinUSB (or libusbK), then Replace Driver",
        "fr": "Dans la fenêtre Zadig :\n"
              "  1.  Options > List All Devices\n"
              "  2.  EyeToy USB camera Namtai (Interface 0)\n"
              "  3.  Cible WinUSB (ou libusbK), puis Replace Driver"},
    "driver.confirm_title": {"en": "Uninstall the driver",
                             "fr": "Désinstaller le pilote"},
    "driver.confirm": {
        "en": "Remove the WinUSB driver installed by EyeToy Studio, and the "
              "certificate added to the trust store?\n\nThe camera will be "
              "unusable until the driver is installed again.",
        "fr": "Retirer le pilote WinUSB installé par EyeToy Studio, et le "
              "certificat ajouté au magasin de confiance ?\n\nLa caméra ne "
              "sera plus utilisable jusqu'à la prochaine installation."},

    # -- camera session and probe ---------------------------------------------
    "session.starting": {"en": "Starting...", "fr": "Démarrage..."},
    "session.ready": {"en": "Camera ready.", "fr": "Caméra prête."},
    "session.usb_unavailable": {"en": "USB stack unavailable: {error}",
                                "fr": "Pile USB indisponible : {error}"},
    "session.recording_interrupted": {
        "en": "recording interrupted: {error}",
        "fr": "enregistrement interrompu : {error}"},
    "probe.not_bound": {
        "en": "Camera detected, but its video interface is not bound to a "
              "WinUSB/libusbK driver.",
        "fr": "Caméra détectée, mais son interface vidéo n'est liée à aucun "
              "pilote WinUSB/libusbK."},
    "probe.access_denied": {
        "en": "Camera detected, but Windows denies access to its video "
              "interface.",
        "fr": "Caméra détectée, mais Windows refuse l'accès à son interface "
              "vidéo."},
    "probe.open_failed": {"en": "Cannot open the camera: {error}",
                          "fr": "Ouverture impossible : {error}"},
    "probe.busy": {"en": "Camera already in use by another program.",
                   "fr": "Caméra déjà utilisée par un autre programme."},
    "probe.not_found": {"en": "No EyeToy detected on the USB bus.",
                        "fr": "Aucune EyeToy détectée sur le bus USB."},
    "probe.not_accessible": {
        "en": "No accessible EyeToy. Check that it is plugged in and that its "
              "driver is installed (Driver button).",
        "fr": "Aucune EyeToy accessible. Vérifier qu'elle est branchée et que "
              "son pilote est installé (bouton Pilote)."},
    "camera.bandwidth": {
        "en": "Not enough USB bandwidth on this port. Plug the camera into "
              "another port, ideally on another controller.",
        "fr": "Bande passante USB insuffisante sur ce port. Brancher la caméra "
              "sur un autre port, idéalement relié à un autre contrôleur."},

    # -- virtual camera ------------------------------------------------------
    "vcam.library_missing": {"en": "pyvirtualcam unavailable: {error}",
                             "fr": "pyvirtualcam indisponible : {error}"},
    "vcam.device": {"en": "Device: {device}", "fr": "Périphérique : {device}"},
    "vcam.no_device": {
        "en": "No virtual camera device registered: {error}",
        "fr": "Aucun périphérique virtuel enregistré : {error}"},
    "vcam.no_winget": {"en": "winget was not found on this system.",
                       "fr": "winget est introuvable sur ce système."},
    "vcam.installing": {
        "en": "Installing OBS Studio (accept the Windows prompt)...",
        "fr": "Installation d'OBS Studio (accepter l'invite Windows)..."},
    "vcam.install_failed": {"en": "Installation failed: {error}",
                            "fr": "Échec de l'installation : {error}"},
    "vcam.winget_failed": {"en": "winget failed: {error}",
                           "fr": "winget a échoué : {error}"},
    "vcam.checking": {"en": "Installed. Checking the device...",
                      "fr": "Installé. Vérification du périphérique..."},

    # -- driver setup ---------------------------------------------------------
    "setup.elevation_refused": {"en": "elevation refused",
                                "fr": "élévation refusée"},
    "setup.launch_failed": {"en": "cannot start: {error}",
                            "fr": "lancement impossible : {error}"},
    "setup.timeout": {"en": "timed out", "fr": "délai dépassé"},
    "setup.exit_code": {"en": "unreadable exit code",
                        "fr": "code de sortie illisible"},
    "setup.no_zadig": {"en": "no Zadig installer in the latest release",
                       "fr": "aucun installeur Zadig dans la dernière version"},
    "setup.bad_signature": {"en": "invalid signature ({status})",
                            "fr": "signature non valide ({status})"},
    "setup.unknown": {"en": "unknown", "fr": "inconnue"},
    "setup.wrong_signer": {"en": "unexpected signer: {signer}",
                           "fr": "signataire inattendu : {signer}"},
    "setup.looking_up": {"en": "Looking for the latest version...",
                         "fr": "Recherche de la dernière version..."},
    "setup.downloading": {"en": "Downloading {name}...",
                          "fr": "Téléchargement de {name}..."},
    "setup.download_progress": {"en": "Downloading... {percent}%",
                                "fr": "Téléchargement... {percent} %"},
    "setup.checking_signature": {"en": "Checking the signature...",
                                 "fr": "Vérification de la signature..."},
    "setup.signature_ok": {"en": "Valid signature - {signer}",
                           "fr": "Signature valide - {signer}"},
    "setup.launching_zadig": {
        "en": "Starting Zadig (accept the Windows prompt)...",
        "fr": "Lancement de Zadig (accepter l'invite Windows)..."},
    "setup.zadig_open": {"en": "Zadig is open. Follow the steps above.",
                         "fr": "Zadig est ouvert. Suivre les étapes ci-dessus."},
    "setup.installer_missing": {"en": "Installer not found in this build.",
                                "fr": "Installeur introuvable dans cette version."},
    "setup.no_ascii_dir": {
        "en": "no extraction folder with an ASCII path; use the manual method",
        "fr": "aucun dossier d'extraction au chemin ASCII ; utiliser la "
              "méthode manuelle"},
    "setup.installing": {
        "en": "Installing the driver (accept the Windows prompt)...",
        "fr": "Installation du pilote (accepter l'invite Windows)..."},
    "setup.install_aborted": {"en": "Installation aborted: {error}",
                              "fr": "Installation abandonnée : {error}"},
    "setup.install_failed": {"en": "Installation failed: {error}",
                             "fr": "Échec de l'installation : {error}"},
    "setup.installed_checking": {"en": "Driver installed. Checking...",
                                 "fr": "Pilote installé. Vérification..."},
    "setup.uninstalling": {
        "en": "Uninstalling (accept the Windows prompt)...",
        "fr": "Désinstallation (accepter l'invite Windows)..."},
    "setup.uninstall_aborted": {"en": "Uninstall aborted: {error}",
                                "fr": "Désinstallation abandonnée : {error}"},
    "setup.uninstall_failed": {"en": "Uninstall failed (code {code}).",
                               "fr": "Échec de la désinstallation (code {code})."},
    "setup.nothing_to_remove": {
        "en": "Nothing to remove: no driver installed by EyeToy Studio.",
        "fr": "Rien à retirer : aucun pilote installé par EyeToy Studio."},
    "setup.removed": {
        "en": "Removed: {drivers} driver(s), {certs} certificate(s). Unplug "
              "and replug the camera.",
        "fr": "Retiré : {drivers} pilote(s), {certs} certificat(s). Débrancher "
              "puis rebrancher la caméra."},
    "setup.code": {"en": "code {code}", "fr": "code {code}"},
    "wdi.-1": {"en": "input/output error", "fr": "erreur d'entrée/sortie"},
    "wdi.-2": {"en": "invalid parameter", "fr": "paramètre invalide"},
    "wdi.-3": {"en": "access denied", "fr": "accès refusé"},
    "wdi.-4": {"en": "device not found", "fr": "périphérique introuvable"},
    "wdi.-5": {"en": "file not found", "fr": "fichier introuvable"},
    "wdi.-6": {"en": "another installation is in progress",
               "fr": "une autre installation est en cours"},
    "wdi.-7": {"en": "timed out", "fr": "délai dépassé"},
    "wdi.-9": {"en": "an installation is already pending",
               "fr": "une installation est déjà en attente"},
    "wdi.-11": {"en": "out of resources", "fr": "ressources insuffisantes"},
    "wdi.-12": {"en": "operation not supported",
                "fr": "opération non prise en charge"},
    "wdi.-14": {"en": "cancelled by the user", "fr": "annulé par l'utilisateur"},
    "wdi.-15": {"en": "administrator rights required",
                "fr": "droits administrateur requis"},
    "wdi.-16": {"en": "32-bit process on 64-bit Windows",
                "fr": "processus 32 bits sur Windows 64 bits"},
    "wdi.-17": {"en": "syntax error in the INF",
                "fr": "erreur de syntaxe dans l'INF"},
    "wdi.-18": {"en": "missing catalogue", "fr": "catalogue manquant"},
    "wdi.-19": {"en": "unsigned driver refused by Windows",
                "fr": "pilote non signé refusé par Windows"},
}
