from loguru import logger
import sys

def setup():
    # 커스텀 레벨 정의 (숫자는 INFO=20 기준, 모두 표시되도록 20 이상으로)
    logger.level("BAR",     no=20, color="<blue>",            icon="▥")
    logger.level("NOENTRY", no=20, color="<blue>",            icon="—")
    logger.level("RISK",    no=21, color="<cyan>",            icon="∑")
    logger.level("BRACKET", no=22, color="<magenta>",         icon="⛓")
    logger.level("RESTORE", no=22, color="<white>",           icon="⟲")
    logger.level("MARGIN",  no=29, color="<yellow><bold>",    icon="¥")
    logger.level("ENTRY",   no=26, color="<green><bold>",     icon="⚡")

    # 기본 sink 교체(컬러/아이콘/레벨표시)
    logger.remove()
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level.icon} {level.name:<7}</level> | "
        "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, format=fmt, colorize=True, level="INFO", backtrace=False, diagnose=False)
