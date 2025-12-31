"""Audio transcoding utilities using PyAV.

This module provides audio format conversion functionality for the music
downloader, supporting various codecs and containers.
"""

from typing import Any

import av
import msgspec

from .models import CodecEnum, ContainerEnum

_PYAV_CODEC_MAP: dict[str, str] = {
    "flac": "flac",
    "alac": "alac",
    "opus": "libopus",
    "vorbis": "libvorbis",
    "mp3": "libmp3lame",
    "aac": "aac",
    "heaac": "aac",
    "ac3": "ac3",
    "eac3": "eac3",
}


class ConversionResult(msgspec.Struct):
    """Result of audio conversion operation."""

    track_location: str
    container: ContainerEnum
    old_track_location: str | None = None
    old_container: ContainerEnum | None = None


def transcode(
    input_path: str,
    output_path: str,
    target_codec: CodecEnum,
    conv_flags: dict[str, Any],
) -> None:
    """Transcodes an audio file using PyAV.

    Args:
        input_path: Path to the input audio file.
        output_path: Path for the output audio file.
        target_codec: Target codec enum for transcoding.
        conv_flags: Additional conversion flags/options.

    Raises:
        TypeError: If output stream is not an AudioStream.
    """
    codec_name = target_codec.name.lower()
    encoder_name = _PYAV_CODEC_MAP.get(codec_name, codec_name)

    input_container = av.open(input_path)
    output_container = av.open(output_path, mode="w")

    try:
        input_stream = input_container.streams.audio[0]
        output_stream = output_container.add_stream(encoder_name)

        if not isinstance(output_stream, av.AudioStream):
            raise TypeError(f"Expected AudioStream, got {type(output_stream).__name__}")

        output_stream.rate = input_stream.rate
        output_stream.layout = input_stream.layout

        # Apply bitrate settings
        bitrate = conv_flags.get("b:a") or conv_flags.get("ab")
        if bitrate:
            if isinstance(bitrate, str) and bitrate.endswith("k"):
                output_stream.bit_rate = int(bitrate[:-1]) * 1000
            elif isinstance(bitrate, int):
                output_stream.bit_rate = bitrate

        # Transcode frames
        for frame in input_container.decode(audio=0):
            for packet in output_stream.encode(frame):
                output_container.mux(packet)

        # Flush encoder
        for packet in output_stream.encode():
            output_container.mux(packet)

    finally:
        input_container.close()
        output_container.close()
