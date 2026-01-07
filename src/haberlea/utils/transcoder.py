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
    # HE-AAC requires profile setting via encoder options
    # Using libfdk_aac if available, otherwise fallback to aac with profile
    "heaac": "libfdk_aac",  # or "aac" with profile=aac_he
    "ac3": "ac3",
    "eac3": "eac3",
    # WAV is PCM, use pcm_s16le or pcm_s24le depending on bit depth
    "wav": "pcm_s16le",
    # MQA, MHA1, MHM1, AC4, NONE are not standard PyAV codecs
    # These should either raise an error or be handled specially
    # For now, we'll let them fall through to the codec_name default
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

    with av.open(input_path) as input_container:
        if not input_container.streams.audio:
            raise ValueError(f"No audio stream found in {input_path}")

        with av.open(output_path, mode="w") as output_container:
            input_stream = input_container.streams.audio[0]
            output_stream = output_container.add_stream(encoder_name)

            if not isinstance(output_stream, av.AudioStream):
                raise TypeError(
                    f"Expected AudioStream, got {type(output_stream).__name__}"
                )

            output_stream.rate = input_stream.rate
            output_stream.layout = input_stream.layout

            # Preserve sample format (bit depth) for lossless codecs
            lossless_codecs = {"flac", "alac", "wav"}
            if (
                codec_name in lossless_codecs
                and hasattr(input_stream, "format")
                and input_stream.format
            ):
                output_stream.format = input_stream.format

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
