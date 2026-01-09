# Heating Oil Monitoring Home Assistant Integration

Custom integration for Home Assistant.
Allowing to monitor usage of heating oil for the house.
It requires a sensor that will provide measure of oil level in the tank.
It is assumed that the sensor will provide air gap value in cm.
The volume calcultion is based on horizontal cylinder tank.

## Development Setup

### Prerequisites

- Docker Desktop
- Visual Studio Code with Dev Containers extension

### Getting Started

1. Clone this repository
2. Open in VS Code
3. Click "Reopen in Container" when prompted
4. Press F5 to start debugging

### Testing

The integration will be automatically loaded in Home Assistant when you start debugging.

Access Home Assistant at: http://localhost:8123

## Installation

Copy the `custom_components/my_integration` directory to your Home Assistant's `custom_components` directory.
