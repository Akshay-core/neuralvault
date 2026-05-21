# Akshay-core
__author__ = "Akshay-core"

# FILE: voice/voice_controller.py
"""
Offline voice interface.
STT: faster-whisper (local model)  — fallback: SpeechRecognition + Google (online)
TTS: pyttsx3 (fully offline)
"""
from app.utils.logger import get_logger

logger = get_logger("voice")

_tts_engine = None


def _get_tts():
    global _tts_engine
    if _tts_engine is None:
        try:
            import pyttsx3
            _tts_engine = pyttsx3.init()
            _tts_engine.setProperty("rate", 165)
            _tts_engine.setProperty("volume", 0.9)
        except Exception as e:
            logger.warning(f"TTS init failed: {e}")
    return _tts_engine


def speak(text: str):
    engine = _get_tts()
    if engine is None:
        logger.warning("TTS not available")
        return
    try:
        engine.say(text[:500])
        engine.runAndWait()
    except Exception as e:
        logger.error(f"TTS error: {e}")


def transcribe_audio(audio_path: str) -> str:
    """Transcribe a wav/mp3 file using faster-whisper (offline)."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, beam_size=3)
        return " ".join(s.text for s in segments).strip()
    except ImportError:
        logger.warning("faster-whisper not installed")
    except Exception as e:
        logger.error(f"Transcription error: {e}")
    return ""


def record_and_transcribe(duration_sec: int = 5) -> str:
    """Record from mic for N seconds and transcribe."""
    try:
        import sounddevice as sd
        import numpy as np
        import scipy.io.wavfile as wav
        import tempfile, os

        sample_rate = 16000
        logger.info(f"Recording {duration_sec}s...")
        audio = sd.rec(
            int(duration_sec * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16"
        )
        sd.wait()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
        wav.write(tmp_path, sample_rate, audio)
        result = transcribe_audio(tmp_path)
        os.unlink(tmp_path)
        return result
    except Exception as e:
        logger.error(f"Recording error: {e}")
        return ""
