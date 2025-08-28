from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Any
from shutil import rmtree
from enum import Enum
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import os
import sys
import ctypes
import json
import time
import datetime
import threading
# import numpy as np


# special classes:
class options:
    class platform:
        windows = sys.platform.startswith("win")
        linux = not windows
    class json:
        indent = 4
    class defaults:
        timeout = 4000 # (ms)


class runtime_properties:
    root: Folder = None
    created_instances: list[SysObj] = []


# static functions:
def get_datetime():
    return datetime.datetime.now().strftime('%d/%m/%Y, %H:%M:%S')

def get_win_file_attrs(path: str):
    """
    Convenience method for retrieving WindowsOS file attributes.
    """
    attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
    if attrs == -1:
        raise FileNotFoundError()
    
    return attrs

def assign_type(path: Path):
    if path.is_dir():
        return Folder(path)
    else:
        return File(path)
    
def delete_path(path: Path):
    if path.is_dir():
        rmtree(path.absolute())
    else:
        os.remove(path.absolute())

def ensure_path(path: str | Path | SysObj) -> Path:
    path_obj = None

    match path:
        case str():
            path_obj = Path(path)
        case SysObj():
            path_obj = path.path

    if isinstance(path, Path):
        path_obj = path

    return path_obj

def parse_path(parent, path) -> Path:
    path = ensure_path(path)
    if parent is None:
        return path
    else:
        assert len(path.parts) == 1, "When using parent-child pathing, child length must be one."
        parent = ensure_path(parent)
        return Path(os.path.join(str(parent), str(path)))


# main classes:
class FileMode(Enum):

    FIND = 1  # (search; errors if does not exist)
    CREATE = 2  # (create; errors if already exists)
    UPDATE = 3  # (open if exists, otherwise create)
    OVERWRITE = 4  # (delete if exists, then create)
    

class SysObj:

    def __init__(self, path: str | Path, *, mode=FileMode.UPDATE, parent: str | Path | SysObj | None=None):
        """
        Base class for system objects. 

        Args:
            path (str | Path): String representation of path or `pathlib.Path` instance.
            mode (FileMode): Mode in which to open the file.
            parent (str | Path | SysObj): Reference to parent. Can be used to separately define a path as `parent/filename`.
            root (bool): Set new object to be root of directory.
        """
        if parent:
            assert ensure_path(parent).is_dir(), "Parent must be a directory."

        path = parse_path(parent, path)
        self._path = path
        self._name: str = self._path.name

        self._was_detected = self._path.exists()
        self._is_dir: bool = self._path.is_dir()

        if runtime_properties.root is None:
            runtime_properties.root = self

        self._parent: SysObj = None

        self._protected = False
        self.__create__ = self._setup_wrapper(self.__create__)

        self.__params__()  # (initialise custom parameters)
        self.__validate__()  # (validate before making real changes to OS file system)

        match mode:
            case FileMode.FIND:
                if not self._was_detected:
                    raise FileNotFoundError()
                
            case FileMode.CREATE:
                if self._was_detected:
                    raise FileExistsError()
                self.__create__()
                
            case FileMode.UPDATE:
                if not self._was_detected:
                    self.__create__()

            case FileMode.OVERWRITE:
                if self._was_detected:
                    self.rm()
                self.__create__()

        self._is_root = os.path.samefile(self.path, runtime_properties.root.path)  # (requires path to reference real object)
        self._parent = None
        self.__configure__()

    def __params__(self):
        """
        Initialise parameters.
        """
        pass
    
    def __validate__(self):
        """
        Called before `__create__()`.
        """
        pass

    def __create__(self):
        """
        Mandatory object creation method.
        """
        raise NotImplementedError()
    
    def __configure__(self):
        """
        Called after `__create__()`.
        """
        pass

    def __repr__(self):
        cls = self.__class__
        return "%s(%s)" % (cls.__name__, self.name)

    @property
    def path(self) -> Path:
        return self._path
    
    @property
    def dirpath(self) -> Path:
        return os.path.dirname(self._path)
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def parent(self) -> SysObj:
        if self._is_root:
            raise PermissionError("Cannot access parent of root.")

        if self._parent is None:
            self._parent = Folder(self.dirpath, mode=FileMode.FIND)

        return self._parent

    @property
    def ishidden(self) -> bool:
        return self._ishidden()

    def _setup_wrapper(self, create_method: Callable):
        def wrapped_create_method():
            runtime_properties.created_instances.append(self.path)
            return create_method()

        return wrapped_create_method

    def rm(self):
        """
        Remove system object. This is only possible if it was **created in Python**.
        """
        if self._protected:
            raise PermissionError()

        delete_path(self.path)

    def _ishidden(self) -> bool:
        """
        Checks platform-specific parameters to determine whether the `SysObj` is hidden.
        """
        if options.platform.windows:
            attrs = get_win_file_attrs(self.path)

            return bool(attrs & 0x02)
        else:
            return self.name.startswith('.')

    def hide(self, hide=True, /):
        """
        Hide or unhide `SysObj`.

        Args:
            hide (bool): Whether to hide the object.

        Notes:
            Throws a `FileExistsError` if hiding a file (`name`) when the hidden version (`.name`) already exists.
        """
        if hide and self.ishidden:
            return  # (nothing needs doing)
        
        if options.platform.windows:
            if hide:
                ctypes.windll.kernel32.SetFileAttributesW(self.path, 0x02)
            else:
                attrs = get_win_file_attrs(self.path)
                ctypes.windll.kernel32.SetFileAttributesW(self.path, attrs & ~0x02)
        else:
            if hide:
                new_path_str = os.path.join(self.dirpath, '.' + self.name)
            else:
                new_path_str = os.path.join(self.dirpath, self.name[1:])

            os.rename(self.path, new_path_str)
            self.__init__(new_path_str, mode=FileMode.FIND)
        

class Folder(SysObj):

    def __validate__(self):
        if self._was_detected:
            assert self._is_dir, "Path does not lead to a `folder`."

    def __create__(self):
        os.mkdir(self.path)

    def __configure__(self):
        self._indexed = False  # (true when searched at least once; prevents unnecessary indexing of children)
        self._directory = {}
        self._activate_listener(
            on_created_event=self._update_dir,
            on_deleted_event=self._update_dir
        )

    def __getattr__(self, target) -> SysObj:
        """
        Prioritises instance attributes, then accesses directory.
        """
        if target in self.__dict__.keys():
            return self.__dict__.get(target)
        else:
            return self._search_dir(target)

    def __getitem__(self, target: str) -> SysObj:
        """
        Ignores instance attributes, goes straight to directory.
        """
        return self._search_dir(target)
    
    @property
    def directory(self) -> dict[str, SysObj]:
        if self._indexed == False:
            self._indexed = True
            self._update_dir()
        
        return self._directory
    
    @property
    def contents(self) -> list[SysObj]:
        return list(self.directory.values())
    
    def _search_dir(self, target: str) -> SysObj:
        if target in self.directory.keys():
            return self.directory.get(target)
        else:
            print("'%s' does not exist in '%s'" % (target, self.path))

    def _update_dir(self):
        contents = os.listdir(self.path)
       
        self._directory = {filename: assign_type(Path(os.path.join(self.path, filename))) for filename in contents}

    def _activate_listener(self, on_created_event: callable, on_deleted_event: callable):
        """
        """
        class FolderEventHandler(FileSystemEventHandler):

            def direct(self, event):
                event_path = os.path.abspath(event.src_path)
                parent_path = os.path.dirname(event_path)

                return os.path.samefile(parent_path, self.folder.path)

            def __init__(self, folder: Folder):
                super().__init__()
                self.folder = folder

            def on_created(self, event):
                if self.direct(event):
                    # print("'%s' created." % event.src_path)
                    on_created_event()

            def on_deleted(self, event):
                if self.direct(event):
                    # print("'%s' deleted." % event.src_path)
                    on_deleted_event()

            def on_modified(self, event):
                if self.direct(event):
                    # print("'%s' modified." % event.src_path)
                    ...
                
        handler = FolderEventHandler(self)
        observer = Observer()
        observer.schedule(handler, self.path, recursive=False)
        observer.start()

    def mkdir(self, target, **kwargs) -> Folder:
        """
        Create new <Folder> object in hierarchy. **MUST NOT CREATE SUBDIRECTORIES** (now enforced by SysObj.__init__)
        """
        f = Folder(target, parent=self.path, **kwargs)
        return f

    def mk(self, target, **kwargs) -> File:
        """
        Create new <File> object in hierarchy. **MUST NOT CREATE SUBDIRECTORIES** (now enforced by SysObj.__init__)
        """
        f = File(target, parent=self.path, **kwargs)
        return f
    
    def join(self, target):
        """
        Append target to `self.path` and return the new path.
        """
        assert len(ensure_path(target).parts) == 1, "target must be a name, not a path."
        return os.path.join(self.path, target)
    
    def get(self, target, timeout=options.defaults.timeout) -> SysObj:
        """
        Another method to obtain subdirectories and files from folder. Features timeout parameter that allows for dynamic searching.

        Args:
            target (str | Path): String representation of path or `pathlib.Path` instance.
            timeout (float, optional): Time to wait for `target` before giving up. Defaults to `options.defaults.timeout`.
        """
        #TODO: add wait-for-file functionality.
        return self._search_dir(target)

    def clear(self):
        """
        Remove all subdirectories.
        """
        for obj in self.contents:
            obj.rm()

    def _wait_for_file(self, target: str, timeout=options.defaults.timeout):
        event = threading.Event()

        class TempHandler(FileSystemEventHandler):
            def on_created(self, *_):
                event.set()

        observer = Observer()
        observer.schedule(TempHandler(), path=self.path)
        observer.start()

        event.wait(timeout=timeout)

        observer.stop()
        observer.join()


class File(SysObj):

    def __params__(self):
        _, self._ext = os.path.splitext(self.name)

    def __validate__(self):
        has_ext = self._ext != ""
        if not has_ext:
            print("'%s' does not have an extension!" % self.name)

        if self._was_detected:
            assert not self._is_dir, "Path does not lead to a `file`."

    def __create__(self):
        open(self.path, 'w').close()

    @property
    def ext(self):
        return self._ext
    
    def write(self, data, mode='w'):
        """
        Passthrough method to write to file.
        """
        with open(self.path, mode=mode) as file:
            file.write(data)

    def read(self) -> str:
        """
        Passthrough method to read from file.
        """
        with open(self.path, 'r') as file:
            return file.read()
        

class JSON(File):

    def __validate__(self):
        super().__validate__()
        assert self.ext.endswith('.json'), "JSON file must end with '.json'"

    def write(self, data: dict):
        with open(self.path, 'w') as file:
            json.dump(data, file, indent=options.json.indent)            

    def read(self) -> dict:
        with open(self.path, 'r') as file:
            return json.load(file)

    def update(self, data: dict):
        old_data = self.read()
        old_data.update(data)
        self.write(old_data)
        

# class NPY(File):

#     def __validate__(self):
#         super().__validate__()
#         assert self.ext.endswith('.npy'), "NPY file must end with '.npy'"

#     def write(self, data: np.ndarray):
#         with open(self.path, 'w') as file:
#             np.save(file, data)

#     def read(self) -> np.ndarray:
#         with open(self.path, 'r') as file:
#             return np.load(file)


runtime_properties.root = Folder('.', mode=FileMode.FIND)
    


if __name__ == "__main__":

    arg = Folder("arg", mode=FileMode.OVERWRITE)
    got = arg.mk('hello.txt')

    # implicit = root.mkdir('implicit')
    # explicit = Folder('explicit', parent=root)

    # file = implicit.mk('implicit.txt')
    # print(implicit.directory)
    # file2 = implicit.mk('hello.txt')
    # print(implicit.directory)
    # file.rm()
    # print(implicit.directory)

    print('number of instances created: %s' % len(runtime_properties.created_instances))

