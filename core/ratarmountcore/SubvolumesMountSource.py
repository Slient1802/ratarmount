#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import stat
import time

from typing import Dict, Iterable, IO, Optional, Tuple, Union

from .MountSource import FileInfo, MountSource
from .utils import overrides


class SubvolumesMountSource(MountSource):
    def __init__(self, mountSources: Dict[str, MountSource], printDebug: int = 0) -> None:
        """
        mountSources : List of mount sources to mount as subfolders.
        """
        self.mountSources: Dict[str, MountSource] = mountSources
        self.printDebug = printDebug

        for name in self.mountSources.keys():
            if '/' in name:
                raise ValueError(f"Mount source names may not contain slashes! ({name})")

        self.rootFileInfo = FileInfo(
            # fmt: off
            size     = 0,
            mtime    = int(time.time()),
            mode     = 0o777 | stat.S_IFDIR,
            linkname = "",
            uid      = os.getuid(),
            gid      = os.getgid(),
            userdata = [None],
            # fmt: on
        )

    def _findMountSource(self, path: str) -> Optional[Tuple[str, str]]:
        path = path.lstrip('/')
        subvolume, subpath = path.split('/', maxsplit=1) if '/' in path else [path, ""]
        return (subvolume, '/' + subpath) if subvolume in self.mountSources else None

    @overrides(MountSource)
    def isImmutable(self) -> bool:
        return all(m.isImmutable() for m in self.mountSources.values())

    @overrides(MountSource)
    def getFileInfo(self, path: str, fileVersion: int = 0) -> Optional[FileInfo]:
        if path == '/':
            return self.rootFileInfo

        if '/' not in path.lstrip('/'):
            return self.rootFileInfo if path.lstrip('/') in self.mountSources else None

        result = self._findMountSource(path)
        if result is None:
            return None
        subvolume, subpath = result

        fileInfo = self.mountSources[subvolume].getFileInfo(subpath, fileVersion=fileVersion)
        if isinstance(fileInfo, FileInfo):
            fileInfo.userdata.append(subvolume)
            return fileInfo

        return None

    @overrides(MountSource)
    def fileVersions(self, path: str) -> int:
        if path == '/':
            return 1

        result = self._findMountSource(path)
        if result is None:
            return 0
        subvolume, subpath = result

        return self.mountSources[subvolume].fileVersions(subpath)

    @overrides(MountSource)
    def listDir(self, path: str) -> Optional[Union[Iterable[str], Dict[str, FileInfo]]]:
        if path == '/':
            return {name: self.rootFileInfo for name in self.mountSources.keys()}

        result = self._findMountSource(path)
        if result is None:
            return None
        subvolume, subpath = result

        return self.mountSources[subvolume].listDir(subpath)

    @overrides(MountSource)
    def open(self, fileInfo: FileInfo) -> IO[bytes]:
        mountSource = fileInfo.userdata.pop()
        try:
            assert isinstance(mountSource, MountSource)
            return mountSource.open(fileInfo)
        finally:
            fileInfo.userdata.append(mountSource)

    @overrides(MountSource)
    def read(self, fileInfo: FileInfo, size: int, offset: int) -> bytes:
        mountSource = fileInfo.userdata.pop()
        try:
            assert isinstance(mountSource, MountSource)
            return mountSource.read(fileInfo, size, offset)
        finally:
            fileInfo.userdata.append(mountSource)

    @overrides(MountSource)
    def getMountSource(self, fileInfo: FileInfo) -> Tuple[str, MountSource, FileInfo]:
        sourceFileInfo = fileInfo.clone()
        subvolume = sourceFileInfo.userdata.pop()

        if subvolume is None or subvolume not in self.mountSources:
            return '/', self, fileInfo
        mountSource = self.mountSources[subvolume]

        subpath, subMountSource, subFileInfo = mountSource.getMountSource(sourceFileInfo)
        return subvolume + '/' + subpath, subMountSource, subFileInfo

    def joinThreads(self):
        for mountSource in self.mountSources:
            if hasattr(mountSource, 'joinThreads'):
                mountSource.joinThreads()
