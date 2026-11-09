"""
CodeScribe (lokal / flexibel), Version 2.1

Erzeugt mit einem lokalen LLM (Ollama, LM Studio u. a.) eine README.md, Docstrings oder ein Code-Audit
für eine Python-Datei. Läuft ohne zusätzliche Pakete (nur Python-Standardbibliothek).

Neu in 2.1:
- Sprachproblem behoben: Die Regeln stehen im System-Feld und komplett in der Zielsprache (keine englischen
  Abschnittsnamen mehr), dazu eine Erinnerung am Ende des Prompts. Der Kontext (num_ctx) wird passend zur
  Dateigröße gesetzt, damit Ollama den Anfang des Prompts nicht still abschneidet. Nach der Antwort wird
  geprüft, ob Sprache stimmt und ob der Prompt gekürzt wurde.
- Zuverlässiger: Streaming (Text erscheint live), Abbrechen-Button, Fortschrittsanzeige, alle Netzwerk-
  Zugriffe im Hintergrund mit Queue, Fehlermeldungen mit Ursache, Syntaxprüfung im Docstring-Modus.
- Komfort: Modellliste vom Server, Presets für Ollama und LM Studio (OpenAI-Format wird unterstützt),
  gemerkte Einstellungen, Warnung vor Servern außerhalb dieses Computers.
- Aufgeräumt: Alle Texte in TEXTE (Deutsch/Englisch, automatisch nach Systemsprache), kein veraltetes
  locale.getdefaultlocale(), robustes Fehlerprotokoll, größenanpassende Dialoge.
"""

from __future__ import annotations

import ast
import ipaddress
import json
import math
import os
import queue
import re
import tempfile
import threading
import time
import tkinter as tk
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Tuple

VERSION = "2.1"
GITHUB_PROFIL_URL = "https://github.com/ABUKICK"
STANDARD_SPRACHE = "de"

STANDARD_URL = "http://localhost:11434/api/generate"
PRESETS: Tuple[Tuple[str, str], ...] = (
    ("Ollama", "http://localhost:11434/api/generate"),
    ("LM Studio", "http://localhost:1234/v1/chat/completions"),
)
MODI = ("readme", "docstrings", "audit")
SPRACHEN = ("en", "de")

KONTEXT_STUFEN = (4096, 8192, 16384, 32768, 65536)
KONTEXT_AUTO_MAX = 32768       # Obergrenze bei "Automatisch" (mehr Kontext braucht viel Arbeitsspeicher)
TOKEN_ZEICHEN = 3.0            # Schätzung: ein Token pro 3 Zeichen (bewusst vorsichtig)
AUSGABE_RESERVE = {"readme": 2500, "audit": 2000}   # erwartete Antwortlänge in Token (Docstrings: ca. Code-Länge)
TEMPERATUR = 0.2               # niedrig: die Dokumentation soll beim Code bleiben
LESE_TIMEOUT = 600             # Sekunden, die der Server für Modell-Laden und Prompt-Verarbeitung brauchen darf
VERBINDUNGS_TIMEOUT = 5
MAX_DATEI_BYTES = 2_000_000
REPARSE_HINWEIS_MAX = 300

# ----------------------------------------------------------------------------
# Design
# ----------------------------------------------------------------------------
BG, CARD, BORDER = "#f4f5f7", "#ffffff", "#d8dce2"
TEXT, MUTED = "#1f2937", "#6b7280"
ACCENT, ACCENT_DARK = "#2563eb", "#1d4ed8"
SUCCESS_COLOR, ERROR_COLOR, WARN_COLOR = "#059669", "#dc2626", "#b45309"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_LINK = ("Segoe UI", 9, "underline")
FONT_TITLE = ("Segoe UI", 20, "bold")


# ----------------------------------------------------------------------------
# Spracherkennung (Systemsprache → Oberfläche und Standard-Zielsprache)
# ----------------------------------------------------------------------------
LANG_DEUTSCH = 0x07   # Windows-Kennung der Hauptsprache (gilt für de-DE, de-AT, de-CH ...)
LANG_ENGLISCH = 0x09


def _windows_sprachcode() -> Optional[str]:
    """Anzeigesprache von Windows: 'de', 'en' oder 'andere'; None, wenn nicht ermittelbar."""
    try:
        import ctypes
        hauptsprache = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except Exception:
        return None
    return {LANG_DEUTSCH: "de", LANG_ENGLISCH: "en"}.get(hauptsprache, "andere")


def _umgebungs_sprachcode(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Sprachcode aus den Umgebungsvariablen (Linux/macOS), z. B. 'de' aus 'de_DE.UTF-8'."""
    env = os.environ if env is None else env
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        wert = env.get(name, "").split(":")[0].strip()
        if not wert or wert in ("C", "POSIX") or wert.startswith("C."):
            continue
        return re.split(r"[_.@-]", wert)[0].lower()
    return None


def erkenne_sprache() -> str:
    """'de' oder 'en' passend zur Anzeigesprache des PCs; ohne Ergebnis gilt Deutsch."""
    code = _windows_sprachcode() if os.name == "nt" else None
    if code is None:
        code = _umgebungs_sprachcode()
    if code is None:
        return STANDARD_SPRACHE
    return "de" if code == "de" else "en"


# ----------------------------------------------------------------------------
# Texte der Oberfläche
# ----------------------------------------------------------------------------
TEXTE: Dict[str, Dict] = {
    "de": {
        "titel": "CodeScribe",
        "untertitel": "KI-Dokumentation mit lokalen Modellen. Der Quellcode geht nur an die eingetragene Adresse.",
        "btn_endpunkte": "API-Endpunkte",
        "btn_info": "Info & Schutz",
        "datei_titel": "Quellcode-Datei",
        "datei_platzhalter": "Keine Datei ausgewählt...",
        "datei_btn": "Datei auswählen (.py)",
        "datei_dialog": "Python-Datei auswählen",
        "datei_schaetzung": "Geschätzter Bedarf: ca. {bedarf} Token ({zeilen} Zeilen Code). {kontext}",
        "kontext_ollama": "Ollama-Kontext: {ctx}.",
        "kontext_extern": "Der Kontext wird im Server bzw. beim Laden des Modells festgelegt.",
        "server_titel": "Lokaler Server & Modell",
        "preset_label": "Server-Vorlage:",
        "preset_eigene": "Eigene Adresse",
        "url_label": "API-Adresse (URL):",
        "modell_label": "Modell:",
        "modell_laden_btn": "Modelle laden / Verbindung prüfen",
        "format_anzeige": "Erkanntes Format: {name}",
        "api_namen": {"ollama_generate": "Ollama (generate)", "ollama_chat": "Ollama (chat)",
                      "openai": "OpenAI-kompatibel (LM Studio u. a.)"},
        "status_pruefe": "Prüfe Verbindung...",
        "status_verbunden": "Verbunden. {n} Modelle gefunden.",
        "status_verbunden_leer": "Verbunden, aber der Server meldet keine Modelle.",
        "status_modell_gewaehlt": " Modell „{modell}“ ausgewählt.",
        "status_modell_fehlt": "Verbunden, aber das Modell „{modell}“ ist nicht installiert. Vorhanden: {liste}",
        "status_fehler": "Server nicht erreichbar ({details}). Bitte Server starten oder Adresse prüfen!",
        "extern_hinweis": "Achtung: Diese Adresse liegt nicht auf diesem Computer. Der Quellcode wird dorthin "
                          "gesendet.",
        "optionen_titel": "Dokumentations-Modus & Sprache",
        "modi": {
            "readme": "Professionelle README.md (Projekt-Doku)",
            "docstrings": "In-Code Docstrings & Type Hints (Google-Style)",
            "audit": "Zusammenfassung / Code-Audit (Zweck & Struktur)",
        },
        "sprache_titel": "Zielsprache für die Dokumentation:",
        "sprache_en": "English",
        "sprache_de": "Deutsch",
        "sprachnamen": {"de": "Deutsch", "en": "Englisch"},
        "kontext_label": "Kontextgröße (Ollama):",
        "kontext_auto": "Automatisch",
        "ergebnis_titel": "Generierte Dokumentation",
        "kopieren": "Kopieren",
        "speichern": "Speichern unter...",
        "leeren": "Leeren",
        "kopiert": "Text kopiert.",
        "generieren": "Dokumentation generieren",
        "abbrechen": "Abbrechen",
        "bereit": "Bereit.",
        "laeuft": "Generiere mit „{modell}“ ... {sek} s, {zeichen} Zeichen erhalten. (Die erste Antwort kann bei "
                  "großen Dateien lange dauern.)",
        "abbrechen_status": "Breche ab...",
        "abgebrochen": "Abgebrochen.",
        "fertig": "Fertig in {sek} s, {zeichen} Zeichen.",
        "fehler_status": "Fehler bei der Generierung.",
        "keine_datei_titel": "Keine Datei",
        "keine_datei_text": "Bitte wähle zuerst eine gültige Python-Datei (.py) aus!",
        "kein_modell_text": "Bitte gib zuerst einen Modell-Namen an oder lade die Modellliste.",
        "datei_zu_gross": "Die Datei ist zu groß ({mb} MB, erlaubt sind {max} MB).",
        "datei_lesefehler": "Die Datei konnte nicht gelesen werden:\n{details}",
        "extern_titel": "Quellcode an anderen Rechner senden?",
        "extern_text": "Der Quellcode wird an „{host}“ gesendet und nicht nur auf diesem Computer verarbeitet.\n\n"
                       "Fortfahren?",
        "kontext_titel": "Kontext zu klein",
        "kontext_text": "Der Prompt braucht etwa {bedarf} Token, das Kontextfenster hat aber nur {ctx}. Dann schneidet "
                        "der Server den Anfang ab, und die Anweisungen (z. B. die Sprachvorgabe) gehen verloren.\n\n"
                        "Tipp: Kontextgröße auf „Automatisch“ oder höher stellen, eine kleinere Datei wählen oder "
                        "ein Modell mit größerem Kontext nutzen.\n\nTrotzdem fortfahren?",
        "fehler_titel": "Fehler",
        "fehler_http": "Der Server antwortet mit Fehler {code}:\n{details}",
        "fehler_verbindung": "Keine Verbindung zum Server:\n{details}",
        "fehler_timeout": "Zeitüberschreitung: Der Server hat {sek} Sekunden lang nichts geliefert.",
        "fehler_server": "Fehler vom Server:\n{details}",
        "fehler_sonst": "Unerwarteter Fehler:\n{details}",
        "pruef_zaun": "Hinweis: Der Code-Zaun (```) wurde entfernt.",
        "pruef_syntax_ok": "Syntaxprüfung: OK.",
        "pruef_syntax_fehler": "Syntaxprüfung: Fehler in {detail}. Bitte vor dem Speichern prüfen!",
        "pruef_sprache_ok": "Sprache der Antwort passt.",
        "pruef_sprache_abweichung": "Hinweis: Die Antwort scheint {ist} zu sein, obwohl {soll} gewählt ist. Erneut "
                                    "generieren oder ein größeres Modell wählen.",
        "pruef_gekuerzt": "Warnung: Der Server hat nur etwa {gelesen} von {geschaetzt} Token gelesen. Der Anfang des "
                          "Prompts wurde vermutlich abgeschnitten. Kontextgröße erhöhen!",
        "speichern_titel": "Dokumentation speichern",
        "kein_inhalt_titel": "Kein Inhalt",
        "kein_inhalt_text": "Es gibt keinen Inhalt zum Speichern!",
        "gespeichert_titel": "Erfolg",
        "gespeichert_text": "Datei erfolgreich gespeichert unter:\n{pfad}",
        "speichern_fehler": "Datei konnte nicht gespeichert werden:\n{details}",
        "dateityp_py": "Python-Dateien",
        "dateityp_md": "Markdown",
        "dateityp_txt": "Textdateien",
        "dateityp_alle": "Alle Dateien",
        "info_titel": "Info, Rechtliches & Projekte",
        "info_entwickler": "Entwickelt von: ABUKICK",
        "info_legal": (
            "Rechtlicher Hinweis & Schutz (Disclaimer):\n"
            "Der Quellcode wird nur an die Adresse gesendet, die du oben einträgst. Bei einem lokalen Server "
            "(localhost) verlässt nichts deinen Computer, und es gibt keine Telemetrie. Trägst du eine fremde "
            "Adresse ein, wird der Code dorthin übertragen (das Tool fragt vorher nach).\n\n"
            "KI-Ausgaben können Fehler enthalten. Prüfe erzeugten Text und Code vor der Verwendung.\n\n"
            "Die Nutzung erfolgt auf eigene Gefahr. Der Entwickler übernimmt keinerlei Haftung für fehlerhafte "
            "Code-Analysen oder Datenverluste."
        ),
        "info_projekte": "Weitere Projekte des Entwicklers:",
        "schliessen": "Schließen",
        "endpunkte_titel": "API-Endpunkte & Lokale Modelle",
        "endpunkte_text": (
            "Hilfreiche API-Endpunkte für lokale LLMs:\n\n"
            "- Ollama (Standard-Dienst):\n"
            "  URL: http://localhost:11434/api/generate\n"
            "  Modelle anzeigen: ollama list (z. B. qwen2.5-coder:7b)\n\n"
            "- LM Studio (OpenAI-kompatibel):\n"
            "  URL: http://localhost:1234/v1/chat/completions\n"
            "  Das Modell wird in LM Studio geladen; dort stellst du auch die Kontextlänge ein.\n\n"
            "- Tipp für große Dateien: Mehr Kontext braucht mehr Arbeitsspeicher. Mit „Automatisch“ wählt "
            "CodeScribe bei Ollama die passende Größe (bis 32768).\n"
            "- Schneller & weniger RAM: ollama pull qwen2.5-coder:1.5b (kleine Modelle halten sich aber "
            "schlechter an Sprachvorgaben)."
        ),
        "absturz_titel": "CodeScribe ist abgestürzt",
        "absturz_text": "Details stehen in der Datei:\n{pfad}",
    },
    "en": {
        "titel": "CodeScribe",
        "untertitel": "AI documentation with local models. Source code only goes to the address you enter.",
        "btn_endpunkte": "API Endpoints",
        "btn_info": "Info & Legal",
        "datei_titel": "Source Code File",
        "datei_platzhalter": "No file selected...",
        "datei_btn": "Select File (.py)",
        "datei_dialog": "Select Python File",
        "datei_schaetzung": "Estimated need: about {bedarf} tokens ({zeilen} lines of code). {kontext}",
        "kontext_ollama": "Ollama context: {ctx}.",
        "kontext_extern": "The context is set in the server or when the model is loaded.",
        "server_titel": "Local Server & Model",
        "preset_label": "Server preset:",
        "preset_eigene": "Custom address",
        "url_label": "API address (URL):",
        "modell_label": "Model:",
        "modell_laden_btn": "Load models / Check connection",
        "format_anzeige": "Detected format: {name}",
        "api_namen": {"ollama_generate": "Ollama (generate)", "ollama_chat": "Ollama (chat)",
                      "openai": "OpenAI-compatible (LM Studio etc.)"},
        "status_pruefe": "Checking connection...",
        "status_verbunden": "Connected. {n} models found.",
        "status_verbunden_leer": "Connected, but the server reports no models.",
        "status_modell_gewaehlt": " Model “{modell}” selected.",
        "status_modell_fehlt": "Connected, but model “{modell}” is not installed. Available: {liste}",
        "status_fehler": "Server unreachable ({details}). Please start the server or check the address!",
        "extern_hinweis": "Warning: This address is not on this computer. The source code will be sent there.",
        "optionen_titel": "Documentation Mode & Language",
        "modi": {
            "readme": "Professional README.md (project docs)",
            "docstrings": "In-code docstrings & type hints (Google style)",
            "audit": "Summary / code audit (purpose & structure)",
        },
        "sprache_titel": "Target language for the documentation:",
        "sprache_en": "English",
        "sprache_de": "Deutsch",
        "sprachnamen": {"de": "German", "en": "English"},
        "kontext_label": "Context size (Ollama):",
        "kontext_auto": "Automatic",
        "ergebnis_titel": "Generated Documentation",
        "kopieren": "Copy",
        "speichern": "Save as...",
        "leeren": "Clear",
        "kopiert": "Text copied.",
        "generieren": "Generate Documentation",
        "abbrechen": "Cancel",
        "bereit": "Ready.",
        "laeuft": "Generating with “{modell}” ... {sek} s, {zeichen} characters received. (The first reply can take "
                  "a long time for large files.)",
        "abbrechen_status": "Cancelling...",
        "abgebrochen": "Cancelled.",
        "fertig": "Done in {sek} s, {zeichen} characters.",
        "fehler_status": "Error during generation.",
        "keine_datei_titel": "No File",
        "keine_datei_text": "Please select a valid Python file (.py) first!",
        "kein_modell_text": "Please enter a model name first or load the model list.",
        "datei_zu_gross": "The file is too large ({mb} MB, maximum is {max} MB).",
        "datei_lesefehler": "The file could not be read:\n{details}",
        "extern_titel": "Send source code to another computer?",
        "extern_text": "The source code will be sent to “{host}” and not only processed on this computer.\n\n"
                       "Continue?",
        "kontext_titel": "Context too small",
        "kontext_text": "The prompt needs about {bedarf} tokens, but the context window is only {ctx}. The server "
                        "would then cut off the beginning and the instructions (e.g. the language rule) would be "
                        "lost.\n\nTip: set the context size to “Automatic” or higher, choose a smaller file, or use "
                        "a model with a larger context.\n\nContinue anyway?",
        "fehler_titel": "Error",
        "fehler_http": "The server responded with error {code}:\n{details}",
        "fehler_verbindung": "No connection to the server:\n{details}",
        "fehler_timeout": "Timeout: The server delivered nothing for {sek} seconds.",
        "fehler_server": "Error from the server:\n{details}",
        "fehler_sonst": "Unexpected error:\n{details}",
        "pruef_zaun": "Note: The code fence (```) was removed.",
        "pruef_syntax_ok": "Syntax check: OK.",
        "pruef_syntax_fehler": "Syntax check: error in {detail}. Please review before saving!",
        "pruef_sprache_ok": "The language of the reply matches.",
        "pruef_sprache_abweichung": "Note: The reply seems to be {ist} although {soll} is selected. Generate again or "
                                    "choose a larger model.",
        "pruef_gekuerzt": "Warning: The server read only about {gelesen} of {geschaetzt} tokens. The beginning of the "
                          "prompt was probably cut off. Increase the context size!",
        "speichern_titel": "Save Documentation",
        "kein_inhalt_titel": "No Content",
        "kein_inhalt_text": "There is no content to save!",
        "gespeichert_titel": "Success",
        "gespeichert_text": "File successfully saved under:\n{pfad}",
        "speichern_fehler": "The file could not be saved:\n{details}",
        "dateityp_py": "Python files",
        "dateityp_md": "Markdown",
        "dateityp_txt": "Text files",
        "dateityp_alle": "All files",
        "info_titel": "Info, Legal & Projects",
        "info_entwickler": "Developed by: ABUKICK",
        "info_legal": (
            "Legal Notice & Protection (Disclaimer):\n"
            "The source code is only sent to the address you enter above. With a local server (localhost) nothing "
            "leaves your computer, and there is no telemetry. If you enter a foreign address, the code is "
            "transmitted there (the tool asks first).\n\n"
            "AI output can contain mistakes. Review generated text and code before use.\n\n"
            "Use at your own risk. The developer assumes no liability for faulty code analyses or data loss."
        ),
        "info_projekte": "More projects by the developer:",
        "schliessen": "Close",
        "endpunkte_titel": "API Endpoints & Local Models",
        "endpunkte_text": (
            "Useful API endpoints for local LLMs:\n\n"
            "- Ollama (default service):\n"
            "  URL: http://localhost:11434/api/generate\n"
            "  List models: ollama list (e.g. qwen2.5-coder:7b)\n\n"
            "- LM Studio (OpenAI-compatible):\n"
            "  URL: http://localhost:1234/v1/chat/completions\n"
            "  The model is loaded in LM Studio; the context length is also set there.\n\n"
            "- Tip for large files: more context needs more RAM. With “Automatic” CodeScribe picks a suitable "
            "size for Ollama (up to 32768).\n"
            "- Faster & less RAM: ollama pull qwen2.5-coder:1.5b (small models follow language rules less "
            "reliably)."
        ),
        "absturz_titel": "CodeScribe crashed",
        "absturz_text": "Details are in the file:\n{pfad}",
    },
}

# ----------------------------------------------------------------------------
# Prompts: Regeln stehen vollständig in der Zielsprache (System-Nachricht) und werden am Ende erinnert
# ----------------------------------------------------------------------------
PROMPTS: Dict[str, Dict] = {
    "de": {
        "intro": "Hier ist der Python-Quellcode der Datei „{name}“:",
        "readme": {
            "system": (
                "Du bist ein erfahrener technischer Redakteur. Schreibe die gesamte Antwort ausschließlich auf "
                "Deutsch: Überschriften, Beschreibungen und Erläuterungen. Code, Dateinamen und Befehle bleiben "
                "unverändert. Erstelle eine professionelle README.md im Markdown-Format zu dem Python-Quellcode, "
                "den der Nutzer sendet. Gib NUR den Markdown-Text der Dokumentation aus, ohne Vorrede, und "
                "wiederhole den Quellcode nicht. Gliedere sie mit diesen deutschen Überschriften: "
                "1. Titel und Kurzbeschreibung, 2. Funktionen, 3. Aufbau und Architektur, "
                "4. Installation und Nutzung, 5. Hinweise. Erfinde keine Lizenz, Abhängigkeiten, Funktionen, "
                "Installationsschritte oder unterstützten Plattformen. Nenne nur Angaben, die sich direkt aus "
                "dem Quellcode oder den bereitgestellten Informationen belegen lassen. Wenn Lizenz oder "
                "Abhängigkeiten nicht erkennbar sind, schreibe ausdrücklich 'Nicht angegeben'."),
            "erinnerung": "Erinnerung: Schreibe die gesamte README.md auf Deutsch, auch alle Überschriften.",
        },
        "docstrings": {
            "system": (
                "Du bist ein Python-Experte. Schreibe alle Docstrings und Kommentare ausschließlich auf Deutsch. "
                "Füge dem Quellcode des Nutzers Docstrings im Google-Stil und Type Hints hinzu. Ändere die "
                "Programmlogik nicht und lass keinen Code weg. Gib ausschließlich den vollständigen, "
                "überarbeiteten Python-Code in einem einzigen Codeblock zurück."),
            "erinnerung": "Erinnerung: Alle Docstrings und Kommentare müssen auf Deutsch sein. Die Logik bleibt "
                          "unverändert.",
        },
        "audit": {
            "system": (
                "Du bist ein Code-Auditor. Schreibe die gesamte Antwort ausschließlich auf Deutsch, auch alle "
                "Überschriften. Erstelle eine strukturierte Übersicht und Zusammenfassung des Python-Codes, den "
                "der Nutzer sendet: Zweck des Skripts, wichtigste Klassen und Funktionen, Optimierungspotenziale."),
            "erinnerung": "Erinnerung: Antworte vollständig auf Deutsch, auch alle Überschriften.",
        },
    },
    "en": {
        "intro": "Here is the Python source code of the file “{name}”:",
        "readme": {
            "system": (
                "You are an experienced technical writer. Write the entire response exclusively in English: "
                "headings, descriptions and explanations. Code, file names and commands stay unchanged. Create a "
                "professional README.md in Markdown format for the Python source code the user sends. Output "
                "ONLY the Markdown text of the documentation, without any preamble, and do not repeat the source "
                "code. Structure it with these headings: 1. Title and short description, 2. Features, "
                "3. Architecture overview, 4. Installation and usage, 5. Notes. Do not invent a license, dependencies, "
                "features, installation steps, or supported platforms. Include only claims supported by the "
                "source code or information provided. If the license or dependencies cannot be determined, "
                "explicitly write 'Not specified'."),
            "erinnerung": "Reminder: Write the entire README.md in English, including all headings.",
        },
        "docstrings": {
            "system": (
                "You are a Python expert. Write all docstrings and comments exclusively in English. Add "
                "Google-style docstrings and type hints to the user's source code. Do not change the program "
                "logic and do not omit any code. Return only the complete, revised Python code in a single code "
                "block."),
            "erinnerung": "Reminder: All docstrings and comments must be in English. The logic stays unchanged.",
        },
        "audit": {
            "system": (
                "You are a code auditor. Write the entire response exclusively in English, including all "
                "headings. Create a structured overview and summary of the Python code the user sends: purpose "
                "of the script, most important classes and functions, and optimization potential."),
            "erinnerung": "Reminder: Answer entirely in English, including all headings.",
        },
    },
}


# ----------------------------------------------------------------------------
# Logik ohne Oberfläche (testbar)
# ----------------------------------------------------------------------------
class Abgebrochen(Exception):
    """Wird geworfen, wenn der Benutzer die Generierung abbricht."""


class ServerFehler(Exception):
    """Fehlermeldung, die der Server selbst im Datenstrom liefert."""


@dataclass
class Auftrag:
    url: str
    api: str                  # 'ollama_generate', 'ollama_chat' oder 'openai'
    modell: str
    system: str
    user: str
    modus: str
    sprache: str
    token_prompt: int
    token_bedarf: int         # Prompt plus erwartete Antwort
    num_ctx: Optional[int]    # nur bei Ollama gesetzt


@dataclass
class Chunk:
    text: str = ""
    fertig: bool = False
    prompt_tokens: Optional[int] = None
    ausgabe_tokens: Optional[int] = None


def schaetze_token(text: str) -> int:
    return int(math.ceil(len(text) / TOKEN_ZEICHEN))


def bereinige_url(url: str) -> str:
    url = url.strip()
    return url if "://" in url else "http://" + url


def basis_url(url: str) -> str:
    """Server-Basisadresse inklusive vorgeschaltetem Pfad, aber ohne bekannten API-Endpunkt."""
    teile = urllib.parse.urlparse(bereinige_url(url))
    pfad = teile.path.rstrip("/")
    niedrig = pfad.lower()
    endpunkte = ("/v1/chat/completions", "/api/generate", "/api/chat", "/v1/models", "/api/tags", "/v1")
    for ende in endpunkte:
        if niedrig.endswith(ende):
            pfad = pfad[:-len(ende)]
            break
    return urllib.parse.urlunparse((teile.scheme, teile.netloc, pfad.rstrip("/"), "", "", ""))


def erkenne_api(url: str) -> str:
    pfad = urllib.parse.urlparse(bereinige_url(url)).path.rstrip("/").lower()
    if pfad.endswith("/chat/completions") or pfad == "/v1" or pfad.endswith("/v1"):
        return "openai"
    if pfad.endswith("/api/chat"):
        return "ollama_chat"
    return "ollama_generate"


def ziel_url(url: str, api: str) -> str:
    """Ergänzt fehlende API-Pfade und erhält Reverse-Proxy-Präfixe wie /proxy."""
    url = bereinige_url(url).rstrip("/")
    pfad = urllib.parse.urlparse(url).path.rstrip("/").lower()
    if api == "openai":
        if pfad.endswith("/chat/completions"):
            return url
        if pfad.endswith("/v1"):
            return url + "/chat/completions"
        return basis_url(url) + "/v1/chat/completions"
    if pfad.endswith("/api/chat") or pfad.endswith("/api/generate"):
        return url
    return basis_url(url) + ("/api/chat" if api == "ollama_chat" else "/api/generate")


def modelle_url(url: str, api: str) -> str:
    return basis_url(url) + ("/v1/models" if api == "openai" else "/api/tags")


def ist_lokal(url: str) -> bool:
    """True, wenn die Adresse auf diesen Computer zeigt (localhost oder Loopback-IP)."""
    host = (urllib.parse.urlparse(bereinige_url(url)).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def host_von(url: str) -> str:
    return urllib.parse.urlparse(bereinige_url(url)).netloc


def modell_vorhanden(modell: str, liste: List[str]) -> bool:
    def norm(m: str) -> str:
        m = m.strip()
        return m[:-7] if m.endswith(":latest") else m
    return norm(modell) in {norm(m) for m in liste}


def zaun(code: str) -> str:
    """Markdown-Zaun, der länger ist als jede Backtick-Folge im Code (sonst bricht der Block vorzeitig ab)."""
    laengste = max((len(m.group()) for m in re.finditer(r"`+", code)), default=0)
    return "`" * max(3, laengste + 1)


def baue_prompt(sprache: str, modus: str, dateiname: str, code: str) -> Tuple[str, str]:
    """(System-Nachricht, Nutzer-Nachricht). Die Erinnerung steht am Ende, dort wird sie am besten beachtet."""
    p = PROMPTS[sprache]
    z = zaun(code)
    user = (f"{p['intro'].format(name=dateiname)}\n\n{z}python\n{code}\n{z}\n\n{p[modus]['erinnerung']}")
    return p[modus]["system"], user


def waehle_kontext(bedarf: int, auswahl: str) -> int:
    """'auto' wählt die kleinste Stufe, die reicht (höchstens KONTEXT_AUTO_MAX); sonst die gewählte Zahl."""
    if auswahl != "auto":
        try:
            return int(auswahl)
        except ValueError:
            pass
    for stufe in KONTEXT_STUFEN:
        if stufe <= KONTEXT_AUTO_MAX and stufe >= bedarf:
            return stufe
    return KONTEXT_AUTO_MAX


def erstelle_auftrag(url: str, modell: str, modus: str, sprache: str, kontext: str,
                     dateiname: str, code: str) -> Auftrag:
    api = erkenne_api(url)
    system, user = baue_prompt(sprache, modus, dateiname, code)
    token_prompt = schaetze_token(system) + schaetze_token(user)
    if modus == "docstrings":  # die Antwort ist so lang wie der Code (plus Docstrings)
        reserve = int(schaetze_token(code) * 1.4) + 500
    else:
        reserve = AUSGABE_RESERVE[modus]
    bedarf = token_prompt + reserve
    num_ctx = waehle_kontext(bedarf, kontext) if api.startswith("ollama") else None
    return Auftrag(url=ziel_url(url, api), api=api, modell=modell.strip(), system=system, user=user, modus=modus,
                   sprache=sprache, token_prompt=token_prompt, token_bedarf=bedarf, num_ctx=num_ctx)


def baue_anfrage(a: Auftrag) -> dict:
    """Request-Body im Format des jeweiligen Servers (Streaming ist immer an)."""
    nachrichten = [{"role": "system", "content": a.system}, {"role": "user", "content": a.user}]
    if a.api == "openai":
        body: dict = {"messages": nachrichten, "stream": True, "temperature": TEMPERATUR}
        if a.modell:
            body["model"] = a.modell
        return body
    optionen: dict = {"temperature": TEMPERATUR}
    if a.num_ctx:
        optionen["num_ctx"] = a.num_ctx
    if a.api == "ollama_chat":
        return {"model": a.modell, "messages": nachrichten, "stream": True, "options": optionen}
    return {"model": a.modell, "system": a.system, "prompt": a.user, "stream": True, "options": optionen}


def parse_stream_zeile(api: str, zeile: bytes) -> Optional[Chunk]:
    """Wertet eine Zeile des Datenstroms aus; None für Leerzeilen. Wirft ServerFehler bei Fehlermeldungen."""
    s = zeile.decode("utf-8", errors="replace").strip()
    if not s:
        return None
    if api == "openai":
        if not s.startswith("data:"):
            return None  # SSE-Kommentare oder event:-Zeilen
        s = s[5:].strip()
        if s == "[DONE]":
            return Chunk(fertig=True)
    try:
        obj = json.loads(s)
    except ValueError:
        return None
    if isinstance(obj, dict) and obj.get("error"):
        fehler = obj["error"]
        raise ServerFehler(fehler.get("message", str(fehler)) if isinstance(fehler, dict) else str(fehler))
    if api == "openai":
        auswahl = (obj.get("choices") or [{}])[0]
        text = (auswahl.get("delta") or {}).get("content") or ""
        nutzung = obj.get("usage") or {}
        return Chunk(text=text, prompt_tokens=nutzung.get("prompt_tokens"),
                     ausgabe_tokens=nutzung.get("completion_tokens"))
    if api == "ollama_chat":
        text = (obj.get("message") or {}).get("content") or ""
    else:
        text = obj.get("response") or ""
    return Chunk(text=text, fertig=bool(obj.get("done")), prompt_tokens=obj.get("prompt_eval_count"),
                 ausgabe_tokens=obj.get("eval_count"))


def parse_modelle(api: str, daten: dict) -> List[str]:
    if api == "openai":
        return [m.get("id", "") for m in daten.get("data", []) if m.get("id")]
    return [m.get("name", "") for m in daten.get("models", []) if m.get("name")]


def oeffne(req: urllib.request.Request, url: str, timeout: float):
    """Öffnet die Anfrage. Lokale Server werden ohne System-Proxy angesprochen (sonst scheitert localhost oft)."""
    if ist_lokal(url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    else:
        opener = urllib.request.build_opener()
    return opener.open(req, timeout=timeout)


def lade_modelle(url: str, post: Callable) -> None:
    """Fragt die Modellliste ab (Hintergrund-Thread). Meldet ('modelle', ok, liste, fehler, url)."""
    api = erkenne_api(url)
    try:
        req = urllib.request.Request(modelle_url(url, api), headers={"User-Agent": "CodeScribe"})
        with oeffne(req, url, VERBINDUNGS_TIMEOUT) as resp:
            daten = json.loads(resp.read().decode("utf-8", errors="replace"))
        post("modelle", True, parse_modelle(api, daten), "", url)
    except Exception as e:
        post("modelle", False, [], str(getattr(e, "reason", e)) or e.__class__.__name__, url)


def generiere(a: Auftrag, post: Callable, abbruch: threading.Event, halter: dict,
              timeout: float = LESE_TIMEOUT) -> None:
    """Sendet die Anfrage und meldet den Datenstrom (Hintergrund-Thread).

    Meldungen: ('chunk', text), ('fertig', {'prompt_tokens':…, 'ausgabe_tokens':…}), ('abgebrochen',),
    ('fehler', art, details). 'halter["antwort"]' erlaubt dem Hauptthread, die Verbindung zu schließen.
    """
    try:
        daten = json.dumps(baue_anfrage(a)).encode("utf-8")
        req = urllib.request.Request(a.url, data=daten, headers={"Content-Type": "application/json",
                                                                  "User-Agent": "CodeScribe"})
        stats = {"prompt_tokens": None, "ausgabe_tokens": None}
        with oeffne(req, a.url, timeout) as resp:
            halter["antwort"] = resp
            # Abbrechen kann unmittelbar vor dem Setzen des Handles erfolgt sein.
            # Direkt nach dem Setzen erneut prüfen und die Verbindung dann schließen.
            if abbruch.is_set():
                try:
                    resp.close()
                finally:
                    raise Abgebrochen
            for zeile in resp:
                if abbruch.is_set():
                    raise Abgebrochen
                chunk = parse_stream_zeile(a.api, zeile)
                if chunk is None:
                    continue
                if chunk.text:
                    post("chunk", chunk.text)
                if chunk.prompt_tokens:
                    stats["prompt_tokens"] = chunk.prompt_tokens
                if chunk.ausgabe_tokens:
                    stats["ausgabe_tokens"] = chunk.ausgabe_tokens
                if chunk.fertig:
                    break
        if abbruch.is_set():
            raise Abgebrochen
        post("fertig", stats)
    except Abgebrochen:
        post("abgebrochen")
    except urllib.error.HTTPError as e:
        try:
            details = e.read().decode("utf-8", errors="replace")[:REPARSE_HINWEIS_MAX]
        except Exception:
            details = e.reason if isinstance(e.reason, str) else ""
        post("fehler", "http", f"{e.code}|{details.strip()}")
    except ServerFehler as e:
        post("fehler", "server", str(e))
    except Exception as e:
        if abbruch.is_set():  # Verbindung wurde absichtlich geschlossen
            post("abgebrochen")
        elif isinstance(e, TimeoutError) or "timed out" in str(e).lower():
            post("fehler", "timeout", str(int(timeout)))
        elif isinstance(e, (urllib.error.URLError, OSError)):
            post("fehler", "verbindung", str(getattr(e, "reason", e)))
        else:
            post("fehler", "sonst", f"{e.__class__.__name__}: {e}")
    finally:
        halter["antwort"] = None


# ---- Dateien und Nachbearbeitung -------------------------------------------
def lese_quelldatei(pfad: str) -> str:
    """Liest eine Textdatei (UTF-8 mit/ohne BOM, sonst Windows-1252); Zeilenenden werden vereinheitlicht."""
    if os.path.getsize(pfad) > MAX_DATEI_BYTES:
        raise ValueError("zu_gross")
    with open(pfad, "rb") as f:
        roh = f.read()
    try:
        text = roh.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = roh.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def vorschlag_dateiname(modus: str, quellpfad: Optional[str]) -> str:
    stamm = os.path.splitext(os.path.basename(quellpfad or "dokumentation"))[0]
    return {"readme": "README.md", "docstrings": f"{stamm}_dokumentiert.py", "audit": f"{stamm}_audit.md"}[modus]


ZAUN_RE = re.compile(r"^(`{3,}|~{3,})[ \t]*[\w+-]*[ \t]*\n(.*?)\n[ \t]*\1[ \t]*$", re.S | re.M)
OFFENER_ZAUN_RE = re.compile(r"^(`{3,}|~{3,})[ \t]*[\w+-]*[ \t]*\n(.*)$", re.S | re.M)


def extrahiere_code(text: str) -> str:
    """Holt den Code aus einem Markdown-Zaun (längster Block); ohne Zaun bleibt der Text unverändert."""
    bloecke = [m.group(2) for m in ZAUN_RE.finditer(text)]
    if bloecke:
        return max(bloecke, key=len).strip("\n")
    m = OFFENER_ZAUN_RE.search(text)  # abgebrochene Ausgabe ohne schließenden Zaun
    if m:
        return m.group(2).strip("\n")
    return text.strip("\n")


def pruefe_syntax(code: str) -> Optional[str]:
    """None, wenn der Code gültiges Python ist; sonst 'Zeile n: Meldung'."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"Zeile {e.lineno}: {e.msg}"
    except ValueError as e:
        return str(e)
    return None


DE_WOERTER = frozenset("der die das und ist nicht mit für von zu den dem ein eine einer auf im als auch wird werden "
                       "wurde dass sich oder bei nach aus über wie zum zur nur kann können sind wenn dieser diese "
                       "dieses".split())
EN_WOERTER = frozenset("the and is of to for with that this are as on be by or from it can will not which at you "
                       "your".split())


def sprache_des_textes(text: str) -> str:
    """'de', 'en', 'gemischt' oder 'unklar' (zu wenig Text) anhand häufiger Funktionswörter."""
    woerter = re.findall(r"[a-zäöüß]+", text.lower())
    de = sum(w in DE_WOERTER for w in woerter)
    en = sum(w in EN_WOERTER for w in woerter)
    if de + en < 25:
        return "unklar"
    if de > 1.5 * en:
        return "de"
    if en > 1.5 * de:
        return "en"
    return "gemischt"


def doku_text(modus: str, text: str) -> str:
    """Der Teil der Ausgabe, der in der Zielsprache sein soll (ohne Code)."""
    if modus == "docstrings":
        code = extrahiere_code(text)
        teile = re.findall(r'"""(.*?)"""', code, re.S) + re.findall(r"#\s*(.*)", code)
        return "\n".join(teile)
    ohne_code = re.sub(r"(`{3,}|~{3,}).*?\1", " ", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", " ", ohne_code)


def prompt_wurde_gekuerzt(geschaetzt: int, num_ctx: Optional[int], gelesen: Optional[int]) -> bool:
    """Ollama kürzt zu lange Prompts still und behält nur das Ende (etwa die Hälfte des Fensters)."""
    if not num_ctx or not gelesen:
        return False
    return geschaetzt > 0.9 * num_ctx and gelesen < 0.7 * geschaetzt


Notiz = Tuple[str, Dict[str, object], str]  # (Text-Schlüssel, Parameter, Stufe: 'ok' | 'info' | 'warn')


def nachbearbeiten(a: Auftrag, text: str, stats: dict) -> Tuple[str, List[Notiz]]:
    """Bereinigt die Ausgabe und prüft sie. Gibt (neuer Text, Notizen) zurück; Texte kommen aus TEXTE."""
    notizen: List[Notiz] = []
    if a.modus == "docstrings":
        code = extrahiere_code(text)
        if code != text.strip("\n"):
            notizen.append(("pruef_zaun", {}, "info"))
            text = code
        fehler = pruefe_syntax(text)
        notizen.append(("pruef_syntax_fehler", {"detail": fehler}, "warn") if fehler
                       else ("pruef_syntax_ok", {}, "ok"))
    if prompt_wurde_gekuerzt(a.token_prompt, a.num_ctx, stats.get("prompt_tokens")):
        notizen.append(("pruef_gekuerzt", {"gelesen": stats["prompt_tokens"], "geschaetzt": a.token_prompt}, "warn"))
    urteil = sprache_des_textes(doku_text(a.modus, text))
    if urteil in ("de", "en") and urteil != a.sprache:
        notizen.append(("pruef_sprache_abweichung", {"ist": urteil, "soll": a.sprache}, "warn"))
    elif urteil == a.sprache:
        notizen.append(("pruef_sprache_ok", {}, "ok"))
    return text, notizen


# ---- Einstellungen -----------------------------------------------------------
def einstellungen_pfad() -> str:
    basis = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(basis, "CodeScribe", "settings.json")


def lade_einstellungen() -> dict:
    try:
        with open(einstellungen_pfad(), encoding="utf-8") as f:
            daten = json.load(f)
        return daten if isinstance(daten, dict) else {}
    except (OSError, ValueError):
        return {}


def speichere_einstellungen(daten: dict) -> None:
    try:
        pfad = einstellungen_pfad()
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(daten, f, indent=2)
    except OSError:
        pass  # Einstellungen sind nicht kritisch


def schreibe_fehlerprotokoll(text: str) -> str:
    """Hängt den Fehler an error_log.txt an (Skript-Ordner, sonst Temp-Ordner); gibt den Pfad zurück."""
    eintrag = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{text}\n\n"
    for ordner in (os.path.dirname(os.path.abspath(__file__)), tempfile.gettempdir()):
        pfad = os.path.join(ordner, "codescribe_error_log.txt")
        try:
            with open(pfad, "a", encoding="utf-8") as f:
                f.write(eintrag)
            return pfad
        except OSError:
            continue
    return ""


# ----------------------------------------------------------------------------
# Design-Helfer
# ----------------------------------------------------------------------------
def apply_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=TEXT, font=FONT)
    style.configure("TButton", padding=(12, 6), font=FONT, background="#e5e7eb", foreground=TEXT,
                    borderwidth=0, focusthickness=0, relief="flat")
    style.map("TButton", background=[("disabled", "#eceef1"), ("active", "#d9dde3")],
              foreground=[("disabled", "#9ca3af")])
    style.configure("Primary.TButton", background=ACCENT, foreground="white", font=FONT_BOLD)
    style.map("Primary.TButton", background=[("disabled", "#93b4f0"), ("active", ACCENT_DARK)],
              foreground=[("disabled", "white")])
    style.configure("Accent.Horizontal.TProgressbar", troughcolor="#e5e7eb", background=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT, bordercolor="#e5e7eb", thickness=6)


def make_card(parent: tk.Misc) -> tk.Frame:
    return tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)


def auto_wrap(label: tk.Label, container: tk.Misc, margin: int = 30) -> None:
    """Passt den Zeilenumbruch eines Labels an die Breite seines Containers an."""
    container.bind("<Configure>", lambda e: label.config(wraplength=max(e.width - margin, 150)), add="+")


class ScrollBereich(tk.Frame):
    """Senkrecht scrollbarer Bereich. Die Bildlaufleiste erscheint nur, wenn der Inhalt höher ist als das Fenster."""

    def __init__(self, parent: tk.Misc, bg: str) -> None:
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.leiste = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.leiste.set)
        self.inhalt = tk.Frame(self.canvas, bg=bg)
        self.fenster_id = self.canvas.create_window((0, 0), window=self.inhalt, anchor="nw")
        self.leiste_sichtbar = False
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inhalt.bind("<Configure>", lambda e: self.aktualisiere())
        self.canvas.bind("<Configure>", self.breite_anpassen)

    def breite_anpassen(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.fenster_id, width=event.width)
        self.aktualisiere()

    def aktualisiere(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        noetig = self.inhalt.winfo_reqheight() > self.canvas.winfo_height()
        if noetig and not self.leiste_sichtbar:
            self.leiste.pack(side=tk.RIGHT, fill=tk.Y)
            self.leiste_sichtbar = True
        elif not noetig and self.leiste_sichtbar:
            self.leiste.pack_forget()
            self.leiste_sichtbar = False
            self.canvas.yview_moveto(0)

    def scroll_einheiten(self, anzahl: int) -> None:
        if self.leiste_sichtbar:
            self.canvas.yview_scroll(anzahl, "units")

    def mausrad(self, event: tk.Event) -> None:
        delta = event.delta
        self.scroll_einheiten(-int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1))

    def mausrad_binden(self, root: tk.Misc) -> None:
        root.bind_all("<MouseWheel>", self.mausrad)
        root.bind_all("<Button-4>", lambda e: self.scroll_einheiten(-1))  # Linux
        root.bind_all("<Button-5>", lambda e: self.scroll_einheiten(1))


# ----------------------------------------------------------------------------
# Hauptanwendung
# ----------------------------------------------------------------------------
class CodeScribeApp:
    def __init__(self, root: tk.Tk, sprache: str = STANDARD_SPRACHE) -> None:
        self.root = root
        self.sprache = sprache if sprache in TEXTE else STANDARD_SPRACHE
        self.t = TEXTE[self.sprache]
        root.title(f"{self.t['titel']} v{VERSION}")
        self.setup_window()
        apply_theme(root)

        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.abbruch = threading.Event()
        self.halter: dict = {"antwort": None}
        self.laeuft = False
        self.start_zeit = 0.0
        self.zeichen = 0
        self.letzter_auftrag: Optional[Auftrag] = None
        self.letzter_quellpfad: Optional[str] = None
        self.dateipfad: Optional[str] = None
        self.quellcode = ""
        self.bestaetigte_hosts: set = set()

        e = lade_einstellungen()
        self.einstellungen = e
        self.var_url = tk.StringVar(value=e.get("url") or STANDARD_URL)
        self.var_modell = tk.StringVar(value=e.get("modell", ""))
        self.var_modus = tk.StringVar(value=e.get("modus") if e.get("modus") in MODI else "readme")
        self.var_sprache = tk.StringVar(value=e.get("doku_sprache") if e.get("doku_sprache") in SPRACHEN
                                        else self.sprache)
        self.var_kontext = tk.StringVar(value=e.get("kontext", "auto"))

        self.baue_oberflaeche()
        for var in (self.var_url, self.var_modus, self.var_sprache, self.var_kontext):
            var.trace_add("write", lambda *args: self.eingaben_geaendert())
        self.eingaben_geaendert()
        self.root.protocol("WM_DELETE_WINDOW", self.beenden)
        self.root.after(50, self.poll_queue)
        self.verbindung_pruefen()

    def setup_window(self) -> None:
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(760, int(sw * 0.9)), min(980, int(sh * 0.9))
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max((sh - h) // 2 - 20, 0)}")
        self.root.minsize(min(540, w), min(460, h))

    # ---------------- Aufbau ----------------
    def baue_oberflaeche(self) -> None:
        t = self.t
        kopf = tk.Frame(self.root, bg=BG)
        kopf.pack(side=tk.TOP, fill=tk.X, padx=28, pady=(16, 6))
        titel_rahmen = tk.Frame(kopf, bg=BG)
        titel_rahmen.pack(fill=tk.X)
        tk.Label(titel_rahmen, text=t["titel"], font=FONT_TITLE, fg=TEXT, bg=BG).pack(side=tk.LEFT)
        rechts = tk.Frame(titel_rahmen, bg=BG)
        rechts.pack(side=tk.RIGHT)
        ttk.Button(rechts, text=t["btn_endpunkte"], command=self.zeige_endpunkte_fenster).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(rechts, text=t["btn_info"], command=self.zeige_info_fenster).pack(side=tk.LEFT)
        untertitel = tk.Label(kopf, text=t["untertitel"], font=FONT_SMALL, fg=MUTED, bg=BG, anchor="w",
                              justify="left")
        untertitel.pack(anchor="w", pady=(2, 0), fill=tk.X)
        auto_wrap(untertitel, kopf, 10)

        # Fuß (unten, immer sichtbar): Status, Fortschritt und die beiden Hauptknöpfe
        fuss = tk.Frame(self.root, bg=BG)
        fuss.pack(side=tk.BOTTOM, fill=tk.X, padx=28, pady=(6, 12))
        knoepfe = tk.Frame(fuss, bg=BG)
        knoepfe.pack(side=tk.RIGHT, padx=(10, 0))
        self.btn_generieren = ttk.Button(knoepfe, text=t["generieren"], style="Primary.TButton",
                                         command=self.generieren_starten)
        self.btn_generieren.pack(side=tk.RIGHT)
        self.btn_abbrechen = ttk.Button(knoepfe, text=t["abbrechen"], command=self.abbrechen, state=tk.DISABLED)
        self.btn_abbrechen.pack(side=tk.RIGHT, padx=(0, 8))
        statusrahmen = tk.Frame(fuss, bg=BG)
        statusrahmen.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_status = tk.Label(statusrahmen, text=t["bereit"], font=FONT_SMALL, fg=MUTED, bg=BG, anchor="w",
                                   justify="left")
        self.lbl_status.pack(fill=tk.X)
        auto_wrap(self.lbl_status, statusrahmen, 10)
        self.fortschritt = ttk.Progressbar(statusrahmen, style="Accent.Horizontal.TProgressbar", mode="indeterminate")
        self.fortschritt.pack(fill=tk.X, pady=(4, 0))

        self.bereich = ScrollBereich(self.root, BG)
        self.bereich.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.bereich.mausrad_binden(self.root)
        self.inhalt = self.bereich.inhalt

        self.baue_datei_karte()
        self.baue_server_karte()
        self.baue_optionen_karte()
        self.baue_ergebnis_karte()

    def karte(self, pady=(4, 4)) -> tk.Frame:
        rahmen = make_card(self.inhalt)
        rahmen.pack(fill=tk.X, padx=28, pady=pady)
        innen = tk.Frame(rahmen, bg=CARD)
        innen.pack(fill=tk.X, padx=20, pady=12)
        return innen

    def baue_datei_karte(self) -> None:
        t = self.t
        innen = self.karte()
        tk.Label(innen, text=t["datei_titel"], font=FONT_BOLD, fg=TEXT, bg=CARD, anchor="w").pack(fill=tk.X)
        zeile = tk.Frame(innen, bg=CARD)
        zeile.pack(fill=tk.X, pady=(6, 0))
        self.entry_pfad = tk.Entry(zeile, font=FONT, relief="flat", bd=0, bg="#f3f4f6", fg=TEXT,
                                   highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        self.entry_pfad.insert(0, t["datei_platzhalter"])
        self.entry_pfad.config(state="readonly")
        self.entry_pfad.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        ttk.Button(zeile, text=t["datei_btn"], command=self.datei_auswaehlen).pack(side=tk.RIGHT, padx=(8, 0))
        self.lbl_schaetzung = tk.Label(innen, text="", font=FONT_SMALL, fg=MUTED, bg=CARD, anchor="w", justify="left")
        self.lbl_schaetzung.pack(fill=tk.X, pady=(6, 0))
        auto_wrap(self.lbl_schaetzung, innen, 10)

    def baue_server_karte(self) -> None:
        t = self.t
        innen = self.karte()
        tk.Label(innen, text=t["server_titel"], font=FONT_BOLD, fg=TEXT, bg=CARD, anchor="w").pack(fill=tk.X, pady=(0, 8))

        z1 = tk.Frame(innen, bg=CARD)
        z1.pack(fill=tk.X, pady=(0, 6))
        tk.Label(z1, text=t["preset_label"], font=FONT, fg=TEXT, bg=CARD, width=18, anchor="w").pack(side=tk.LEFT)
        namen = [name for name, _ in PRESETS] + [t["preset_eigene"]]
        self.cmb_preset = ttk.Combobox(z1, values=namen, state="readonly", width=24)
        self.cmb_preset.pack(side=tk.LEFT)
        self.cmb_preset.bind("<<ComboboxSelected>>", lambda e: self.preset_gewaehlt())

        z2 = tk.Frame(innen, bg=CARD)
        z2.pack(fill=tk.X, pady=(0, 6))
        tk.Label(z2, text=t["url_label"], font=FONT, fg=TEXT, bg=CARD, width=18, anchor="w").pack(side=tk.LEFT)
        tk.Entry(z2, textvariable=self.var_url, font=FONT, relief="flat", bg="#f3f4f6", fg=TEXT,
                 highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.lbl_format = tk.Label(innen, text="", font=FONT_SMALL, fg=MUTED, bg=CARD, anchor="w")
        self.lbl_format.pack(fill=tk.X)
        self.lbl_extern = tk.Label(innen, text="", font=FONT_SMALL, fg=WARN_COLOR, bg=CARD, anchor="w", justify="left")
        self.lbl_extern.pack(fill=tk.X)
        auto_wrap(self.lbl_extern, innen, 10)

        z3 = tk.Frame(innen, bg=CARD)
        z3.pack(fill=tk.X, pady=(8, 0))
        tk.Label(z3, text=t["modell_label"], font=FONT, fg=TEXT, bg=CARD, width=18, anchor="w").pack(side=tk.LEFT)
        self.cmb_modell = ttk.Combobox(z3, textvariable=self.var_modell, values=[], width=30)
        self.cmb_modell.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(z3, text=t["modell_laden_btn"], command=self.verbindung_pruefen).pack(side=tk.RIGHT, padx=(8, 0))

        statusrahmen = tk.Frame(innen, bg="#f9fafb", highlightthickness=1, highlightbackground=BORDER)
        statusrahmen.pack(fill=tk.X, pady=(10, 0))
        self.lbl_server_status = tk.Label(statusrahmen, text=t["status_pruefe"], font=FONT_BOLD, fg=MUTED,
                                          bg="#f9fafb", anchor="w", justify="left", padx=10, pady=6)
        self.lbl_server_status.pack(fill=tk.X)
        auto_wrap(self.lbl_server_status, statusrahmen, 24)

    def baue_optionen_karte(self) -> None:
        t = self.t
        innen = self.karte()
        tk.Label(innen, text=t["optionen_titel"], font=FONT_BOLD, fg=TEXT, bg=CARD, anchor="w").pack(fill=tk.X, pady=(0, 6))
        for modus in MODI:
            tk.Radiobutton(innen, text=t["modi"][modus], variable=self.var_modus, value=modus, font=FONT, bg=CARD,
                           activebackground=CARD, anchor="w").pack(fill=tk.X, pady=2)
        tk.Frame(innen, bg=BORDER, height=1).pack(fill=tk.X, pady=(12, 10))

        tk.Label(innen, text=t["sprache_titel"], font=FONT_BOLD, fg=TEXT, bg=CARD, anchor="w").pack(fill=tk.X, pady=(0, 4))
        sprachzeile = tk.Frame(innen, bg=CARD)
        sprachzeile.pack(fill=tk.X)
        tk.Radiobutton(sprachzeile, text=t["sprache_en"], variable=self.var_sprache, value="en", font=FONT, bg=CARD,
                       activebackground=CARD, anchor="w").pack(side=tk.LEFT, padx=(0, 20))
        tk.Radiobutton(sprachzeile, text=t["sprache_de"], variable=self.var_sprache, value="de", font=FONT, bg=CARD,
                       activebackground=CARD, anchor="w").pack(side=tk.LEFT)

        kontextzeile = tk.Frame(innen, bg=CARD)
        kontextzeile.pack(fill=tk.X, pady=(12, 0))
        tk.Label(kontextzeile, text=t["kontext_label"], font=FONT, fg=TEXT, bg=CARD).pack(side=tk.LEFT)
        self.cmb_kontext = ttk.Combobox(kontextzeile, values=[t["kontext_auto"]] + [str(s) for s in KONTEXT_STUFEN],
                                        state="readonly", width=14)
        self.cmb_kontext.pack(side=tk.LEFT, padx=(8, 0))
        self.cmb_kontext.set(t["kontext_auto"] if self.var_kontext.get() == "auto" else self.var_kontext.get())
        self.cmb_kontext.bind("<<ComboboxSelected>>", lambda e: self.kontext_gewaehlt())

    def baue_ergebnis_karte(self) -> None:
        t = self.t
        innen = self.karte(pady=(4, 12))
        titel_zeile = tk.Frame(innen, bg=CARD)
        titel_zeile.pack(fill=tk.X, pady=(0, 6))
        tk.Label(titel_zeile, text=t["ergebnis_titel"], font=FONT_BOLD, fg=TEXT, bg=CARD, anchor="w").pack(side=tk.LEFT)
        knoepfe = tk.Frame(titel_zeile, bg=CARD)
        knoepfe.pack(side=tk.RIGHT)
        ttk.Button(knoepfe, text=t["kopieren"], command=self.kopieren).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(knoepfe, text=t["speichern"], command=self.speichern).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(knoepfe, text=t["leeren"], command=self.leeren).pack(side=tk.LEFT)

        text_rahmen = tk.Frame(innen, bg=BORDER, highlightthickness=1, highlightbackground=BORDER)
        text_rahmen.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.txt_ausgabe = tk.Text(text_rahmen, wrap=tk.WORD, font=("Consolas", 10), height=14, relief="flat", bd=0,
                                   bg="#ffffff", fg=TEXT)
        leiste = ttk.Scrollbar(text_rahmen, orient="vertical", command=self.txt_ausgabe.yview)
        self.txt_ausgabe.configure(yscrollcommand=leiste.set)
        leiste.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_ausgabe.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.lbl_pruefung = tk.Label(innen, text="", font=FONT_SMALL, fg=MUTED, bg=CARD, anchor="w", justify="left")
        self.lbl_pruefung.pack(fill=tk.X, pady=(8, 0))
        auto_wrap(self.lbl_pruefung, innen, 10)

    # ---------------- Eingaben, Vorlagen, Schätzung ----------------
    def kontext_wert(self) -> str:
        return "auto" if self.var_kontext.get() in ("auto", self.t["kontext_auto"]) else self.var_kontext.get()

    def kontext_gewaehlt(self) -> None:
        auswahl = self.cmb_kontext.get()
        self.var_kontext.set("auto" if auswahl == self.t["kontext_auto"] else auswahl)

    def preset_gewaehlt(self) -> None:
        index = self.cmb_preset.current()
        if 0 <= index < len(PRESETS):
            self.var_url.set(PRESETS[index][1])
            self.verbindung_pruefen()

    def eingaben_geaendert(self) -> None:
        """Aktualisiert Format-Anzeige, Warnhinweis für fremde Server, Vorlagen-Auswahl und Bedarfsschätzung."""
        t = self.t
        url = self.var_url.get()
        api = erkenne_api(url)
        self.lbl_format.config(text=t["format_anzeige"].format(name=t["api_namen"][api]))
        self.lbl_extern.config(text="" if ist_lokal(url) else t["extern_hinweis"])
        passend = [i for i, (_, preset_url) in enumerate(PRESETS) if preset_url == url.strip()]
        if passend:
            self.cmb_preset.current(passend[0])
        else:
            self.cmb_preset.set(t["preset_eigene"])
        self.aktualisiere_schaetzung()

    def aktualisiere_schaetzung(self) -> None:
        t = self.t
        if not self.quellcode:
            self.lbl_schaetzung.config(text="")
            return
        a = erstelle_auftrag(self.var_url.get(), self.var_modell.get(), self.var_modus.get(), self.var_sprache.get(),
                             self.kontext_wert(), os.path.basename(self.dateipfad or ""), self.quellcode)
        kontext = (t["kontext_ollama"].format(ctx=a.num_ctx) if a.num_ctx else t["kontext_extern"])
        zeilen = self.quellcode.count("\n") + 1
        warnung = a.num_ctx is not None and a.token_bedarf > a.num_ctx
        self.lbl_schaetzung.config(
            text=t["datei_schaetzung"].format(bedarf=f"{a.token_bedarf:,}".replace(",", "."), zeilen=zeilen,
                                              kontext=kontext),
            fg=WARN_COLOR if warnung else MUTED)

    # ---------------- Datei ----------------
    def datei_auswaehlen(self) -> None:
        t = self.t
        pfad = filedialog.askopenfilename(
            title=t["datei_dialog"],
            initialdir=self.einstellungen.get("ordner") or None,
            filetypes=[(t["dateityp_py"], "*.py"), (t["dateityp_alle"], "*.*")])
        if not pfad:
            return
        try:
            code = lese_quelldatei(pfad)
        except ValueError:
            mb = os.path.getsize(pfad) / 1_000_000
            messagebox.showerror(t["fehler_titel"], t["datei_zu_gross"].format(mb=f"{mb:.1f}", max=MAX_DATEI_BYTES / 1_000_000))
            return
        except OSError as e:
            messagebox.showerror(t["fehler_titel"], t["datei_lesefehler"].format(details=e))
            return
        self.dateipfad, self.quellcode = pfad, code
        self.einstellungen["ordner"] = os.path.dirname(pfad)
        self.entry_pfad.config(state="normal")
        self.entry_pfad.delete(0, tk.END)
        self.entry_pfad.insert(0, os.path.basename(pfad))
        self.entry_pfad.config(state="readonly")
        self.aktualisiere_schaetzung()

    # ---------------- Verbindung und Modellliste ----------------
    def verbindung_pruefen(self) -> None:
        self.lbl_server_status.config(text=self.t["status_pruefe"], fg=MUTED)
        url = self.var_url.get()
        threading.Thread(target=lade_modelle, args=(url, self.post), daemon=True).start()

    def modelle_anzeigen(self, ok: bool, liste: List[str], fehler: str, url: str) -> None:
        t = self.t
        if url != self.var_url.get():
            return  # veraltete Antwort (Adresse wurde inzwischen geändert)
        if not ok:
            self.lbl_server_status.config(text=t["status_fehler"].format(details=fehler), fg=ERROR_COLOR)
            return
        self.cmb_modell.config(values=liste)
        if not liste:
            self.lbl_server_status.config(text=t["status_verbunden_leer"], fg=WARN_COLOR)
            return
        text = t["status_verbunden"].format(n=len(liste))
        modell = self.var_modell.get().strip()
        if not modell:
            self.var_modell.set(liste[0])
            self.lbl_server_status.config(text=text + t["status_modell_gewaehlt"].format(modell=liste[0]), fg=SUCCESS_COLOR)
        elif modell_vorhanden(modell, liste):
            self.lbl_server_status.config(text=text, fg=SUCCESS_COLOR)
        else:
            self.lbl_server_status.config(
                text=t["status_modell_fehlt"].format(modell=modell, liste=", ".join(liste[:8])), fg=WARN_COLOR)

    # ---------------- Generieren ----------------
    def generieren_starten(self) -> None:
        t = self.t
        if self.laeuft:
            return
        if not self.dateipfad or not os.path.exists(self.dateipfad):
            messagebox.showwarning(t["keine_datei_titel"], t["keine_datei_text"])
            return
        try:  # die Datei wird frisch gelesen, falls sie sich geändert hat
            self.quellcode = lese_quelldatei(self.dateipfad)
        except (OSError, ValueError) as e:
            messagebox.showerror(t["fehler_titel"], t["datei_lesefehler"].format(details=e))
            return
        url, modell = self.var_url.get(), self.var_modell.get().strip()
        a = erstelle_auftrag(url, modell, self.var_modus.get(), self.var_sprache.get(), self.kontext_wert(),
                             os.path.basename(self.dateipfad), self.quellcode)
        if not modell and a.api != "openai":
            messagebox.showwarning(t["fehler_titel"], t["kein_modell_text"])
            return
        host = host_von(url)
        verbindungsziel = urllib.parse.urlparse(bereinige_url(url))
        bestaetigungsschluessel = (verbindungsziel.scheme.lower(), host.lower())
        if not ist_lokal(url) and bestaetigungsschluessel not in self.bestaetigte_hosts:
            if not messagebox.askyesno(t["extern_titel"], t["extern_text"].format(host=host), icon="warning"):
                return
            self.bestaetigte_hosts.add(bestaetigungsschluessel)
        if a.num_ctx is not None and a.token_bedarf > a.num_ctx:
            if not messagebox.askyesno(t["kontext_titel"], t["kontext_text"].format(
                    bedarf=f"{a.token_bedarf:,}".replace(",", "."), ctx=a.num_ctx), icon="warning"):
                return

        self.letzter_auftrag = a
        # Speichervorschlag muss zum gestarteten Auftrag passen, auch wenn der Nutzer
        # während der Generierung Modus oder ausgewählte Quelldatei ändert.
        self.letzter_quellpfad = self.dateipfad
        self.abbruch.clear()
        self.zeichen = 0
        self.start_zeit = time.time()
        self.laeuft = True
        self.txt_ausgabe.delete("1.0", tk.END)
        self.lbl_pruefung.config(text="")
        self.setze_laufzustand(True)
        self.aktualisiere_status_laufend()
        self.speichere_alles()
        threading.Thread(target=generiere, args=(a, self.post, self.abbruch, self.halter), daemon=True).start()

    def setze_laufzustand(self, laeuft: bool) -> None:
        self.btn_generieren.config(state=tk.DISABLED if laeuft else tk.NORMAL)
        self.btn_abbrechen.config(state=tk.NORMAL if laeuft else tk.DISABLED)
        if laeuft:
            self.fortschritt.start(15)
        else:
            self.fortschritt.stop()

    def aktualisiere_status_laufend(self) -> None:
        """Zeigt Laufzeit und Menge während der Generierung; ruft sich jede halbe Sekunde selbst auf."""
        if not self.laeuft:
            return
        sek = int(time.time() - self.start_zeit)
        modell = self.letzter_auftrag.modell if self.letzter_auftrag else ""
        self.lbl_status.config(text=self.t["laeuft"].format(modell=modell or "?", sek=sek, zeichen=self.zeichen), fg=ACCENT)
        self.root.after(500, self.aktualisiere_status_laufend)

    def abbrechen(self) -> None:
        if not self.laeuft:
            return
        self.abbruch.set()
        self.lbl_status.config(text=self.t["abbrechen_status"], fg=MUTED)
        self.verbindung_schliessen()

    def verbindung_schliessen(self) -> None:
        """Schließt die offene Verbindung, damit der Hintergrund-Thread sofort aufwacht."""
        antwort = self.halter.get("antwort")
        if antwort is not None:
            try:
                antwort.close()
            except Exception:
                pass

    # ---------------- Queue (nur Hauptthread) ----------------
    def post(self, *msg) -> None:
        self.q.put(msg)

    def poll_queue(self) -> None:
        chunks: List[str] = []
        for _ in range(500):
            try:
                msg = self.q.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "chunk":
                chunks.append(msg[1])
                continue
            if chunks:
                self.ausgabe_anhaengen("".join(chunks))
                chunks = []
            self.handle(msg)
        if chunks:
            self.ausgabe_anhaengen("".join(chunks))
        self.root.after(50, self.poll_queue)

    def handle(self, msg: tuple) -> None:
        art = msg[0]
        if art == "fertig":
            self.generierung_beenden("fertig", msg[1])
        elif art == "abgebrochen":
            self.generierung_beenden("abgebrochen")
        elif art == "fehler":
            self.generierung_beenden("fehler", msg[1], msg[2])
        elif art == "modelle":
            self.modelle_anzeigen(*msg[1:])

    def ausgabe_anhaengen(self, text: str) -> None:
        self.txt_ausgabe.insert(tk.END, text)
        self.txt_ausgabe.see(tk.END)
        self.zeichen += len(text)

    def generierung_beenden(self, art: str, *args) -> None:
        t = self.t
        self.laeuft = False
        self.setze_laufzustand(False)
        sek = int(time.time() - self.start_zeit)
        if art == "abgebrochen":
            self.lbl_status.config(text=t["abgebrochen"], fg=MUTED)
        elif art == "fehler":
            self.lbl_status.config(text=t["fehler_status"], fg=ERROR_COLOR)
            messagebox.showerror(t["fehler_titel"], self.fehlertext(args[0], args[1]))
        else:
            self.lbl_status.config(text=t["fertig"].format(sek=sek, zeichen=self.zeichen), fg=SUCCESS_COLOR)
            self.nachbearbeiten_und_pruefen(args[0])

    def fehlertext(self, art: str, details: str) -> str:
        t = self.t
        if art == "http":
            code, _, text = details.partition("|")
            return t["fehler_http"].format(code=code, details=text or "-")
        if art == "timeout":
            return t["fehler_timeout"].format(sek=details)
        return t[{"verbindung": "fehler_verbindung", "server": "fehler_server"}.get(art, "fehler_sonst")].format(
            details=details)

    def nachbearbeiten_und_pruefen(self, stats: dict) -> None:
        if not self.letzter_auftrag:
            return
        roh = self.txt_ausgabe.get("1.0", tk.END).rstrip("\n")
        neu, notizen = nachbearbeiten(self.letzter_auftrag, roh, stats)
        if neu != roh:
            self.txt_ausgabe.delete("1.0", tk.END)
            self.txt_ausgabe.insert(tk.END, neu)
        zeilen = []
        for schluessel, params, stufe in notizen:
            params = dict(params)
            if "ist" in params:
                namen = self.t["sprachnamen"]
                params["ist"], params["soll"] = namen[params["ist"]], namen[params["soll"]]
            zeilen.append(self.t[schluessel].format(**params))
        warnung = any(stufe == "warn" for _, _, stufe in notizen)
        self.lbl_pruefung.config(text="\n".join(zeilen), fg=WARN_COLOR if warnung else SUCCESS_COLOR)

    # ---------------- Kopieren, Speichern, Leeren ----------------
    def ausgabe_text(self) -> str:
        return self.txt_ausgabe.get("1.0", tk.END).strip()

    def kopieren(self) -> None:
        inhalt = self.ausgabe_text()
        if not inhalt:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(inhalt)
        self.lbl_status.config(text=self.t["kopiert"], fg=ACCENT)

    def leeren(self) -> None:
        self.txt_ausgabe.delete("1.0", tk.END)
        self.lbl_pruefung.config(text="")

    def speichern(self) -> None:
        t = self.t
        inhalt = self.ausgabe_text()
        if not inhalt:
            messagebox.showwarning(t["kein_inhalt_titel"], t["kein_inhalt_text"])
            return
        # Ergebnis immer anhand des Auftrags speichern, der dieses Ergebnis erzeugt hat.
        modus = self.letzter_auftrag.modus if self.letzter_auftrag else self.var_modus.get()
        quellpfad = self.letzter_quellpfad if self.letzter_auftrag else self.dateipfad
        vorschlag = vorschlag_dateiname(modus, quellpfad)
        typen = {"readme": [(t["dateityp_md"], "*.md"), (t["dateityp_txt"], "*.txt")],
                 "audit": [(t["dateityp_md"], "*.md"), (t["dateityp_txt"], "*.txt")],
                 "docstrings": [(t["dateityp_py"], "*.py")]}[modus]
        pfad = filedialog.asksaveasfilename(
            title=t["speichern_titel"], initialfile=vorschlag,
            defaultextension=os.path.splitext(vorschlag)[1],
            filetypes=typen + [(t["dateityp_alle"], "*.*")])
        if not pfad:
            return
        try:
            with open(pfad, "w", encoding="utf-8", newline="\n") as f:
                f.write(inhalt + "\n")
        except OSError as e:
            messagebox.showerror(t["fehler_titel"], t["speichern_fehler"].format(details=e))
            return
        messagebox.showinfo(t["gespeichert_titel"], t["gespeichert_text"].format(pfad=pfad))

    # ---------------- Dialoge ----------------
    def erstelle_dialog(self, titel: str) -> Tuple[tk.Toplevel, tk.Frame]:
        fenster = tk.Toplevel(self.root, bg=CARD)
        fenster.title(titel)
        fenster.resizable(False, False)
        inhalt = tk.Frame(fenster, bg=CARD)
        inhalt.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        return fenster, inhalt

    def dialog_anzeigen(self, fenster: tk.Toplevel) -> None:
        """Größe aus dem Inhalt, mittig über dem Hauptfenster."""
        fenster.update_idletasks()
        fw, fh = fenster.winfo_reqwidth(), fenster.winfo_reqheight()
        x = self.root.winfo_x() + (self.root.winfo_width() - fw) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - fh) // 2
        fenster.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        fenster.transient(self.root)
        fenster.grab_set()

    def zeige_info_fenster(self) -> None:
        t = self.t
        fenster, inhalt = self.erstelle_dialog(t["info_titel"])
        tk.Label(inhalt, text=f"{t['titel']} v{VERSION}", font=FONT_BOLD, fg=TEXT, bg=CARD).pack(anchor="w", pady=(0, 4))
        tk.Label(inhalt, text=t["info_entwickler"], font=FONT_SMALL, fg=ACCENT, bg=CARD).pack(anchor="w", pady=(0, 12))
        tk.Label(inhalt, text=t["info_legal"], font=FONT_SMALL, fg=TEXT, bg="#f9fafb", justify="left", anchor="w",
                 padx=10, pady=8, wraplength=440).pack(fill=tk.X, pady=(0, 14))
        tk.Label(inhalt, text=t["info_projekte"], font=FONT_SMALL, fg=TEXT, bg=CARD, justify="left",
                 anchor="w").pack(anchor="w", pady=(0, 2))
        link = tk.Label(inhalt, text=GITHUB_PROFIL_URL, font=FONT_LINK, fg=ACCENT, bg=CARD, cursor="hand2", anchor="w")
        link.pack(anchor="w", pady=(0, 16))
        link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_PROFIL_URL))
        ttk.Button(inhalt, text=t["schliessen"], command=fenster.destroy).pack(anchor="e")
        self.dialog_anzeigen(fenster)

    def zeige_endpunkte_fenster(self) -> None:
        t = self.t
        fenster, inhalt = self.erstelle_dialog(t["endpunkte_titel"])
        tk.Label(inhalt, text=t["endpunkte_text"], font=FONT_SMALL, fg=TEXT, bg="#f3f4f6", justify="left", anchor="w",
                 padx=10, pady=8, wraplength=470).pack(fill=tk.X, pady=(0, 16))
        ttk.Button(inhalt, text=t["schliessen"], command=fenster.destroy).pack(anchor="e")
        self.dialog_anzeigen(fenster)

    # ---------------- Beenden ----------------
    def speichere_alles(self) -> None:
        self.einstellungen.update({"url": self.var_url.get().strip(), "modell": self.var_modell.get().strip(),
                                   "modus": self.var_modus.get(), "doku_sprache": self.var_sprache.get(),
                                   "kontext": self.kontext_wert()})
        speichere_einstellungen(self.einstellungen)

    def beenden(self) -> None:
        if self.laeuft:
            self.abbruch.set()
            self.verbindung_schliessen()
        self.speichere_alles()
        self.root.destroy()


def main() -> None:
    sprache = erkenne_sprache()
    try:
        root = tk.Tk()
        CodeScribeApp(root, sprache)
        root.mainloop()
    except Exception:
        pfad = schreibe_fehlerprotokoll(traceback.format_exc())
        t = TEXTE[sprache]
        try:
            messagebox.showerror(t["absturz_titel"], t["absturz_text"].format(pfad=pfad or "-"))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
