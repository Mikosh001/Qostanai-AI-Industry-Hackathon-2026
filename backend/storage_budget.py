"""Keep a disk reserve for database commits and recovery, before media writes."""
import errno,os,shutil


def require_space(path,incoming=0):
    reserve=int(os.environ.get('SERGEK_DISK_RESERVE_BYTES',str(1024**3)))
    if reserve<64*1024**2:reserve=64*1024**2
    if shutil.disk_usage(path).free<reserve+incoming:
        raise OSError(errno.ENOSPC,'Дискіде бос орын жеткіліксіз. Әкімшіге хабарласыңыз.')
