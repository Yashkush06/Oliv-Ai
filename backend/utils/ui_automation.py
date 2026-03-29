import ctypes
import ctypes.wintypes
import logging

logger = logging.getLogger(__name__)

# Windows UI Automation Constants
UIA_NamePropertyId = 30005
UIA_BoundingRectanglePropertyId = 30001

# Load UI Automation DLL
try:
    uia = ctypes.WinDLL('UIAutomationCore.dll')
except Exception as e:
    logger.error(f"Failed to load UIAutomationCore.dll: {e}")
    uia = None

def find_element_by_name(name_to_find: str):
    """
    Find a Windows UI element by its name property using UI Automation (ctypes).
    Returns (x, y) center coordinates or None.
    """
    if not uia:
        return None

    # This is a simplified implementation of walking the UIA tree via ctypes.
    # For a production-grade zero-dep version, we use the IUIAutomation interface.
    
    # Note: Implementing the full COM interface via ctypes is complex.
    # We'll provide a robust helper that uses PowerShell's built-in UIA 
    # as a reliable zero-dependency bridge if direct ctypes is too brittle.
    
    import subprocess
    import json

    ps_script = f"""
    Add-Type -AssemblyName UIAutomationClient
    $root = [Windows.Automation.AutomationElement]::RootElement
    $condition = New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::NameProperty, "{name_to_find}")
    $element = $root.FindFirst([Windows.Automation.TreeScope]::Descendants, $condition)
    if ($element) {{
        $rect = $element.Current.BoundingRectangle
        $res = @{{
            x = [int]($rect.Left + ($rect.Width / 2))
            y = [int]($rect.Top + ($rect.Height / 2))
            name = $element.Current.Name
        }}
        $res | ConvertTo-Json
    }}
    """
    try:
        process = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10
        )
        if process.stdout.strip():
            data = json.loads(process.stdout)
            return data['x'], data['y']
    except Exception as e:
        logger.error(f"UI Automation via PowerShell failed: {e}")
    
    return None
