import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.duketopceo.pplx"
  ipcTarget: "io.github.duketopceo.pplx"

  property bool statusKnown: false
  property bool installed: false
  property bool authed: false
  property bool hasSearched: false
  property bool isSearching: false
  property var hits: []
  property string lastError: ""
  property int elapsedMs: 0
  property real animPulse: 0.0

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color urgent: Color.urgent
  readonly property color accent: Color.accent
  readonly property color muted: Color.muted
  readonly property color cardBg: Qt.rgba(fg.r, fg.g, fg.b, 0.04)
  readonly property color cardBorder: Qt.rgba(fg.r, fg.g, fg.b, 0.08)
  readonly property string pluginRoot: {
    var p = Qt.resolvedUrl(".").toString()
    if (p.indexOf("file://") === 0) p = p.substring(7)
    if (p.length > 1 && p.charAt(p.length - 1) === "/") p = p.substring(0, p.length - 1)
    return p
  }

  readonly property string statusText: !statusKnown ? "CHECKING" : !installed ? "NOT INSTALLED" : !authed ? "NO KEY" : "READY"
  readonly property color statusColor: !statusKnown ? muted : (installed && authed ? accent : urgent)

  // Absolute interpreter + minimal env: a PATH-preceding shadow "python3"
  // must never run here. HOME passes through so the helpers' omaseal
  // keyring lookup resolves under ~, PERPLEXITY_API_KEY so the helper's
  // env-var resolution order works — the key lives only in the child
  // env, never on argv, never rendered, never logged.
  readonly property string py: "/usr/bin/python3"
  readonly property var procEnv: ({
    "PATH": "/usr/bin:/bin",
    "HOME": Quickshell.env("HOME"),
    "PERPLEXITY_API_KEY": Quickshell.env("PERPLEXITY_API_KEY"),
    "XDG_RUNTIME_DIR": null,
    "LANG": null,
    "LC_ALL": "C"
  })

  NumberAnimation on animPulse {
    from: 0.3
    to: 1.0
    duration: 1400
    loops: Animation.Infinite
    running: root.opened
    easing.type: Easing.InOutSine
  }

  // Both helpers os.setsid() into their own session group, so a
  // group-kill reaches the whole tree even if Python is stuck in a wait.
  function groupKill(proc) {
    if (!proc.running) return
    var pid = proc.pid
    if (pid > 0)
      Quickshell.execDetached(["/usr/bin/kill", "-KILL", "--", "-" + pid.toString()])
    proc.signal(9)
  }

  function refreshStatus() {
    if (!statusProc.running) {
      statusProc.running = true
      statusDeadline.restart()
    }
  }

  function submitQuery() {
    var q = queryField.text.trim()
    if (q.length === 0 || searchProc.running) return
    hits = []
    lastError = ""
    elapsedMs = 0
    hasSearched = true
    isSearching = true
    // The query is a single argv element — no shell, no interpolation.
    searchProc.command = [root.py, root.pluginRoot + "/bin/pplx_search.py", q]
    searchDeadline.restart()
    searchProc.running = true
  }

  function killSearch() {
    groupKill(searchProc)
    searchDeadline.stop()
    isSearching = false
  }

  function openHit(url) {
    // xdg-open only gets a single argv element with an http(s) scheme.
    if (typeof url !== "string" || !/^https?:\/\//.test(url)) return
    Quickshell.execDetached(["/usr/bin/xdg-open", url])
  }

  onOpenedChanged: {
    if (opened) refreshStatus()
    else { queryField.text = ""; killSearch() }
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // Status probe: {"installed": bool, "authed": bool} — no network.
  Process {
    id: statusProc
    command: [root.py, root.pluginRoot + "/bin/pplx_status.py"]
    clearEnvironment: true
    environment: root.procEnv
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        statusDeadline.stop()
        try {
          if (!text || text.trim().length === 0) return
          if (text.length > 300000) return
          var data = JSON.parse(text)
          root.installed = !!data.installed
          root.authed = !!data.authed
          root.statusKnown = true
        } catch (e) {}
      }
    }
    onExited: statusDeadline.stop()
  }

  Timer {
    id: statusDeadline
    interval: 8000
    onTriggered: root.groupKill(statusProc)
  }

  Timer {
    id: statusTimer
    interval: 30000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refreshStatus()
  }

  // Search: {"ok","needs_key","installed","hits":[{title,url,domain,
  // snippet,date}],"error","elapsed_ms"} — spawned only on submit.
  Process {
    id: searchProc
    command: [root.py, root.pluginRoot + "/bin/pplx_search.py"]
    clearEnvironment: true
    environment: root.procEnv
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        searchDeadline.stop()
        root.isSearching = false
        try {
          if (!text || text.trim().length === 0) {
            if (root.lastError === "") root.lastError = "no output from helper"
            return
          }
          if (text.length > 300000) {
            root.lastError = "helper output exceeded byte cap"
            return
          }
          var data = JSON.parse(text)
          if (data === null || typeof data !== "object") {
            root.lastError = "unexpected helper output"
            return
          }
          root.installed = !!data.installed
          if (data.needs_key) root.authed = false
          if (data.ok === true) {
            // A completed search proves the key resolved.
            root.authed = true
            root.hits = (data.hits || []).slice(0, 8)
            root.elapsedMs = Number(data.elapsed_ms) || 0
            root.lastError = ""
          } else {
            root.hits = []
            root.lastError = (typeof data.error === "string" && data.error.length > 0)
                ? data.error : "search failed"
          }
        } catch (e) {
          root.hits = []
          root.lastError = "unparseable helper output"
        }
      }
    }
    onExited: { searchDeadline.stop(); root.isSearching = false }
  }

  Timer {
    id: searchDeadline
    // Helper's own backstop is JOB_DEADLINE_S=15s; watchdog gets slack above it.
    interval: 17000
    onTriggered: {
      root.groupKill(searchProc)
      root.isSearching = false
      root.lastError = "search timed out"
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰍉"
    tooltipText: "pplx · Perplexity Search"
    // Paints the glyph in the urgent color while the tool can't search.
    active: root.statusKnown && (!root.installed || !root.authed)
    onPressed: function (b) { root.refreshStatus(); root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: queryField
    contentWidth: panel.fittedContentWidth(Style.space(440), 500)
    contentHeight: panel.fittedContentHeight(mainColumn.implicitHeight, 620)

    PanelKeyCatcher {
      anchors.fill: parent
      // While the query editor holds focus every key belongs to it —
      // Enter submits and Escape closes inside the TextInput itself.
      blocked: queryField.activeFocus
      onCloseRequested: root.close()
      onActivateRequested: if (queryField.text.trim().length > 0) root.submitQuery()
      onTabRequested: function (direction) { root.switchPanel(direction) }

      Column {
        id: mainColumn
        width: parent.width
        spacing: Style.space(12)

        // Header card: title + status pill
        Rectangle {
          width: parent.width
          height: 64
          radius: 10
          color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.08)
          border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.25)
          border.width: 1

          RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 12

            Text {
              textFormat: Text.PlainText
              text: "󰍉"
              color: root.accent
              font.pixelSize: 24
            }

            Column {
              Layout.fillWidth: true
              spacing: 2
              Text {
                textFormat: Text.PlainText
                text: "PERPLEXITY SEARCH"
                color: root.fg
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Text {
                textFormat: Text.PlainText
                text: "Quick-ask web answers via the pplx CLI"
                color: root.muted
                font.pixelSize: 10
              }
            }

            Rectangle {
              height: 22
              width: Math.max(64, pillText.implicitWidth + 18)
              radius: 11
              color: Qt.rgba(root.statusColor.r, root.statusColor.g, root.statusColor.b, 0.15)
              Text {
                textFormat: Text.PlainText
                id: pillText
                anchors.centerIn: parent
                text: root.statusText
                color: root.statusColor
                font.pixelSize: 9
                font.bold: true
                opacity: (root.isSearching || !root.statusKnown) ? root.animPulse : 1.0
              }
            }
          }
        }

        // Quick-ask row: single-line editor; Enter submits, Escape closes
        Rectangle {
          visible: root.installed
          width: parent.width
          height: Style.space(36)
          radius: 8
          color: root.cardBg
          border.color: queryField.activeFocus ? root.accent : root.cardBorder
          border.width: 1

          TextInput {
            id: queryField
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 10
            verticalAlignment: TextInput.AlignVCenter
            clip: true
            color: root.fg
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            selectByMouse: true
            onAccepted: root.submitQuery()
            Keys.onEscapePressed: root.close()

            Text {
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              visible: queryField.text.length === 0
              text: "Ask anything…"
              textFormat: Text.PlainText
              color: root.muted
              font: queryField.font
              elide: Text.ElideRight
            }
          }
        }

        // Indeterminate "…" line while a search is in flight
        Text {
          visible: root.isSearching
          text: "Searching…"
          textFormat: Text.PlainText
          color: root.muted
          font.pixelSize: Style.font.bodySmall
          opacity: root.animPulse
        }

        // Error line — hidden while a state pane is already explaining
        Text {
          visible: root.lastError !== "" && !root.isSearching && root.installed && root.authed
          width: parent.width
          text: root.lastError
          textFormat: Text.PlainText
          color: root.urgent
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }

        // State pane: setup when pplx missing, key-setup when no key —
        // one card, conditional copy.
        Rectangle {
          visible: root.statusKnown && (!root.installed || !root.authed)
          width: parent.width
          height: stateColumn.implicitHeight + 24
          radius: 8
          color: root.cardBg
          border.color: root.cardBorder
          border.width: 1

          Column {
            id: stateColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 12
            spacing: 4
            Text {
              text: !root.installed ? "pplx CLI not found" : "No Perplexity API key"
              textFormat: Text.PlainText
              color: root.fg
              font.pixelSize: Style.font.bodySmall
              font.bold: true
            }
            Text {
              width: parent.width
              text: !root.installed
                  ? "Install pplx from github.com/perplexityai/perplexity-cli releases"
                  : "Set PERPLEXITY_API_KEY, or: omaseal set perplexity api-key"
              textFormat: Text.PlainText
              color: root.muted
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.Wrap
            }
          }
        }

        // Count + latency line; doubles as the empty-result state
        Text {
          visible: root.hasSearched && !root.isSearching && root.lastError === ""
              && root.installed && root.authed
          width: parent.width
          text: root.hits.length > 0
              ? root.hits.length + " hits · " + root.elapsedMs + " ms"
              : "No results."
          textFormat: Text.PlainText
          color: root.muted
          font.pixelSize: 10
        }

        // Results list
        Flickable {
          visible: root.hits.length > 0
          width: parent.width
          height: Math.min(Style.space(400), resultsColumn.implicitHeight)
          contentWidth: width
          contentHeight: resultsColumn.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentHeight > height

          Column {
            id: resultsColumn
            width: parent.width
            spacing: Style.space(8)

            Repeater {
              model: root.hits
              delegate: Rectangle {
                width: resultsColumn.width
                height: hitColumn.implicitHeight + 16
                radius: 8
                color: root.cardBg
                border.color: hitArea.containsMouse
                    ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.4)
                    : root.cardBorder
                border.width: 1

                Column {
                  id: hitColumn
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.top: parent.top
                  anchors.margins: 8
                  spacing: 2

                  Text {
                    width: parent.width
                    text: modelData.title
                    textFormat: Text.PlainText
                    color: root.fg
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                    elide: Text.ElideRight
                  }
                  Text {
                    width: parent.width
                    text: modelData.domain + (modelData.date ? " · " + modelData.date : "")
                    textFormat: Text.PlainText
                    color: root.muted
                    font.pixelSize: 10
                    elide: Text.ElideRight
                  }
                  Text {
                    visible: modelData.snippet !== ""
                    width: parent.width
                    text: modelData.snippet
                    textFormat: Text.PlainText
                    color: root.muted
                    font.pixelSize: 10
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    clip: true
                  }
                }

                MouseArea {
                  id: hitArea
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.openHit(modelData.url)
                }
              }
            }
          }
        }
      }
    }
  }
}
