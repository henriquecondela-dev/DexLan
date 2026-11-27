"""Pipelines GStreamer.

Host:     fonte do ecrã -> H.264 -> appsink (o Python envia pela rede)
Receiver: appsrc (vem da rede) -> descodificador -> janela
"""
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

Gst.init(None)


def tem(element):
    return Gst.ElementFactory.find(element) is not None


def codificadores(fps, kbps, hw=False):
    gop = fps * 2  # uma keyframe a cada 2 segundos
    software = [
        ("x264enc", f"x264enc tune=zerolatency speed-preset=ultrafast bitrate={kbps} "
                    f"key-int-max={gop} threads=2 ! video/x-h264,profile=baseline"),
        ("openh264enc", f"openh264enc bitrate={kbps * 1000} gop-size={gop} complexity=low "
                        f"usage-type=screen ! video/x-h264,profile=baseline"),
    ]
    hardware = [
        ("vah264lpenc", f"vah264lpenc bitrate={kbps} key-int-max={gop} rate-control=cbr"),
        ("vah264enc", f"vah264enc bitrate={kbps} key-int-max={gop} rate-control=cbr"),
    ]
    return hardware + software if hw else software


def escolher_codificador(fps, kbps, hw=False):
    for name, desc in codificadores(fps, kbps, hw):
        if tem(name):
            return name, desc
    raise RuntimeError("nenhum codificador H.264 instalado (corre 'dexlan setup')")


def escolher_descodificador():
    for name in ("avdec_h264", "openh264dec", "decodebin"):
        if tem(name):
            return name
    raise RuntimeError("nenhum descodificador H.264 instalado (corre 'dexlan setup')")


def pipeline_host(source, width, height, fps, kbps, hw=False):
    name, encoder = escolher_codificador(fps, kbps, hw)
    return name, (
        f"{source} ! queue leaky=downstream max-size-buffers=2 ! "
        f"videoconvert ! videoscale ! videorate drop-only=true ! "
        f"video/x-raw,format=I420,width={width},height={height},framerate={fps}/1 ! "
        f"{encoder} ! h264parse config-interval=-1 ! "
        f"video/x-h264,stream-format=byte-stream,alignment=au ! "
        f"appsink name=sink emit-signals=true sync=false max-buffers=8 drop=false")


def pipeline_receiver(sink="gtksink name=view sync=false"):
    decoder = escolher_descodificador()
    return decoder, (
        f"appsrc name=src is-live=true format=time do-timestamp=true "
        f"caps=video/x-h264,stream-format=byte-stream,alignment=au ! "
        f"queue max-size-buffers=3 leaky=downstream ! h264parse ! {decoder} ! "
        f"identity name=probe ! videoconvert ! {sink}")


def pedir_keyframe(pipeline):
    event = Gst.Structure.new_from_string("GstForceKeyUnit, all-headers=(boolean)true")
    pipeline.get_by_name("sink").send_event(Gst.Event.new_custom(Gst.EventType.CUSTOM_UPSTREAM, event))
