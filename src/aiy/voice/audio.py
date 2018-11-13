import contextlib
import subprocess
import threading
import itertools
import wave

from collections import namedtuple


class AudioFormat(namedtuple('AudioFormat',
                             ['sample_rate_hz', 'num_channels', 'bytes_per_sample'])):
    @property
    def bytes_per_second(self):
        return self.sample_rate_hz * self.num_channels * self.bytes_per_sample

AudioFormat.CD = AudioFormat(sample_rate_hz=44100, num_channels=2, bytes_per_sample=2)


def wave_set_format(wav_file, fmt):
    wav_file.setnchannels(fmt.num_channels)
    wav_file.setsampwidth(fmt.bytes_per_sample)
    wav_file.setframerate(fmt.sample_rate_hz)


def wave_get_format(wav_file):
    return AudioFormat(sample_rate_hz=wav_file.getframerate(),
                       num_channels=wav_file.getnchannels(),
                       bytes_per_sample=wav_file.getsampwidth())


def arecord(fmt, filetype='raw', filename=None, device='default'):
    """ Microphone -> File | Stdout."""
    if fmt is None:
        raise ValueError('Format must be specified.')

    if filetype not in ('wav', 'raw', 'voc', 'au'):
        raise ValueError('File type must be wav, raw, voc, or au.')

    cmd = ['arecord', '-q',
           '-t', filetype,
           '-D', device,
           '-c', str(fmt.num_channels),
           '-f', 's%d' % (8 * fmt.bytes_per_sample),
           '-r', str(fmt.sample_rate_hz)]

    if filename is not None:
        cmd.append(filename)

    return cmd


def aplay(fmt, filetype='raw', filename=None, device='default'):
    """File | Stdin -> Speaker."""
    if filetype == 'raw' and fmt is None:
        raise ValueError('Format must be specified for raw data.')

    cmd = ['aplay', '-q', '-t', filetype, '-D', device]
    if fmt is not None:
        cmd.extend(['-c', str(fmt.num_channels),
                    '-f', 's%d' % (8 * fmt.bytes_per_sample),
                    '-r', str(fmt.sample_rate_hz)])
    if filename is not None:
        cmd.append(filename)
    return cmd

def record_file_async(fmt, filename, filetype, device='default'):
    cmd = arecord(fmt, filetype=filetype, filename=filename, device=device)
    return subprocess.Popen(cmd)


def record_file(fmt, filename, filetype, wait, device='default'):
    if wait is None:
        raise ValueError('Wait callback must be specified.')

    process = record_file_async(fmt, filename, filetype, device)
    wait()
    process.terminate()
    process.wait()


def play_wav_async(filename_or_bytes):
    if isinstance(filename_or_bytes, (bytes, bytearray)):
        cmd = aplay(fmt=None, filetype='wav', filename=None)
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        process.stdin.write(filename_or_bytes)
        return process

    if isinstance(filename_or_bytes, str):
        cmd = aplay(fmt=None, filetype='wav', filename=filename_or_bytes)
        return subprocess.Popen(cmd)

    raise ValueError('Must be filename or byte-like object')


def play_wav(filename_or_bytes):
    play_wav_async(filename_or_bytes).wait()


def play_raw_async(fmt, filename_or_bytes):
    if isinstance(filename_or_bytes, (bytes, bytearray)):
        cmd = aplay(fmt=fmt, filetype='raw')
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        process.stdin.write(filename_or_bytes)
        return process

    if isinstance(filename_or_bytes, str):
        cmd = aplay(fmt=fmt, filetype='raw', filename=filename)
        return subprocess.Popen(cmd)

    raise ValueError('Must be filename or byte-like object')


def play_raw(fmt, filename_or_bytes):
    play_raw_async(fmt, filename).wait()


class Recorder:

    def __init__(self, ):
        self._done = threading.Event()
        self._started = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.join()

    def record(self, fmt, chunk_duration_sec, device='default',
               num_chunks=None,
               on_start=None, on_stop=None, filename=None):

        chunk_size = int(chunk_duration_sec * fmt.bytes_per_second)
        cmd = arecord(fmt=fmt, device=device)

        wav_file = None
        if filename:
            wav_file = wave.open(filename, 'wb')
            wave_set_format(wav_file, fmt)

        self._process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        self._started.set()
        if on_start:
            on_start()
        try:
            for _ in (range(num_chunks) if num_chunks else itertools.count()):
                if self._done.is_set():
                    break
                data = self._process.stdout.read(chunk_size)
                if not data:
                    break
                if wav_file:
                    wav_file.writeframes(data)
                yield data
        finally:
            self._process.stdout.close()
            if on_stop:
                on_stop()
            if wav_file:
                wav_file.close()

    def done(self):
        self._done.set()

    def join(self):
        self._started.wait()
        self._process.wait()



class Player:

    def __init__(self):
        self._started = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.join()

    def popen(self, cmd, **kwargs):
        self._process = subprocess.Popen(cmd, **kwargs)
        self._started.set()
        return self._process

    def join(self):
        self._started.wait()
        self._process.wait()


class FilePlayer(Player):

    def __init__(self):
        super().__init__()

    def play_raw(fmt, filename, device='default'):
        self.popen(aplay(fmt=fmt, filetype='raw', filename=filename, device=device))


    def play_wav(filename, device='default'):
        self.popen(aplay(fmt=None, filetype='wav', filename=filename, device=device))

class BytesPlayer(Player):

    def __init__(self):
        super().__init__()

    def play(self, fmt, device='default'):
        process = self.popen(aplay(fmt=fmt, filetype='raw', device=device), stdin=subprocess.PIPE)

        def push(data):
            if data:
                process.stdin.write(data)
            else:
                process.stdin.close()
        return push