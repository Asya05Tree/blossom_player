import subprocess

# Собранный .exe (blossom.spec) запускается с console=False — без этого флага
# каждый subprocess.run() консольной программы (ffmpeg, ffprobe, fpcalc)
# на миг открывает и сразу закрывает собственное окно консоли, потому что
# у родителя-без-консоли Windows создаёт новую для дочернего процесса.
NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
