Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Chạy main.py ở chế độ ẩn dưới nền
WshShell.Run "cmd /c """ & currentDir & "\.venv\Scripts\python.exe"" """ & currentDir & "\main.py""", 0, False
Set WshShell = Nothing
