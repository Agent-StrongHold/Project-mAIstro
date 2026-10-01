---
inventory-delta: |
  Added gateway model discovery failure handling in the setup wizard (Setup.tsx):
  - Added state variables: modelsDiscovered, modelError, fallbackAcknowledged, fetchKey
  - Modified the model fetching useEffect to set modelsDiscovered and modelError based on success/failure
  - Added ApiError import to parse error status and provide user-friendly messages
  - Modified the UI to show:
      * Label indicating whether models are discovered or fallback
      * Error message when model discovery fails
      * Retry button to re-attempt model discovery
      * Fallback acknowledgment checkbox and warning when using fallback models
  - Updated the Next button disability condition to require fallback acknowledgment when model discovery failed
  - Fixed typos in FALLBACK_MODELS array (claede -> claude)
---