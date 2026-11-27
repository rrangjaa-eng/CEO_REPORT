// File System Access API 중 크롬에만 있는 부분 (TS DOM 정의에 없음)
interface FileSystemHandlePermissionDescriptor {
  mode?: "read" | "readwrite";
}
interface FileSystemHandle {
  queryPermission(descriptor?: FileSystemHandlePermissionDescriptor): Promise<PermissionState>;
  requestPermission(descriptor?: FileSystemHandlePermissionDescriptor): Promise<PermissionState>;
}
interface DirectoryPickerOptions {
  id?: string;
  mode?: "read" | "readwrite";
}
interface Window {
  showDirectoryPicker(options?: DirectoryPickerOptions): Promise<FileSystemDirectoryHandle>;
}
