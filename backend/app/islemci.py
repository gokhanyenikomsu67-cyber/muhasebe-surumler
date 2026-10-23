"""Ağır okuma işlerini (PDF fatura) ayrı işlemlerde çalıştırır: toplu yüklemede bilgisayarın bütün çekirdekleri kullanılır.

Python tek işlemde aynı anda tek çekirdek kullanır; binlerce PDF yüklenirken okuma sırayla gidiyordu. İşlem sayısı
.env'de MUHASEBE_ISLEMCI ile değiştirilir (1 = ayrı işlem yok). Havuz bozulursa iş aynı işlemde yapılır."""
import multiprocessing
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

_HAVUZ: ProcessPoolExecutor | None = None
_KILIT = threading.Lock()


def _ana_islemi_izle(ana_pid: int):
    """Okuma işlemi, program (ana işlem) kapanınca ya da zorla sonlandırılınca kendiliğinden kapanır."""
    def bekle():
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32
            tutamak = k.OpenProcess(0x00100000, False, ana_pid)  # SYNCHRONIZE
            if tutamak:
                k.WaitForSingleObject(tutamak, 0xFFFFFFFF)
        else:
            import time
            while os.getppid() == ana_pid:
                time.sleep(2)
        os._exit(0)
    threading.Thread(target=bekle, daemon=True).start()


def islem_sayisi() -> int:
    try:
        return max(1, int(os.environ["MUHASEBE_ISLEMCI"]))
    except (KeyError, ValueError):
        return min(4, max(1, (os.cpu_count() or 2) - 1))


def calistir(is_, *args):
    global _HAVUZ
    n = islem_sayisi()
    if n <= 1:
        return is_(*args)
    with _KILIT:
        if _HAVUZ is None:
            _HAVUZ = ProcessPoolExecutor(n, mp_context=multiprocessing.get_context("spawn"),
                                         initializer=_ana_islemi_izle, initargs=(os.getpid(),))
        havuz = _HAVUZ
    try:
        return havuz.submit(is_, *args).result()
    except BrokenProcessPool:
        with _KILIT:
            if _HAVUZ is havuz:
                _HAVUZ = None
        return is_(*args)


def kapat():
    global _HAVUZ
    with _KILIT:
        if _HAVUZ is not None:
            _HAVUZ.shutdown(wait=True, cancel_futures=True)
            _HAVUZ = None
