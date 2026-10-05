/* Fake AuraFriday native-messaging shim for Wine.
 * Emits one Chrome native-messaging framed JSON message on stdout,
 * pointing the Fusion add-in at the local MCP-Link emulator.
 * Build: x86_64-w64-mingw32-gcc -O2 -o shim.exe shim.c
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>

int main(void) {
    const char *json =
        "{\"mcpServers\":{\"local\":{\"url\":\"http://127.0.0.1:8757/sse\","
        "\"headers\":{\"Authorization\":\"Bearer fusion360-mcp-local-token\","
        "\"Content-Type\":\"application/json\"}}}}";
    uint32_t len = (uint32_t)strlen(json);
    fwrite(&len, 4, 1, stdout);
    fwrite(json, 1, len, stdout);
    fflush(stdout);
    return 0;
}
