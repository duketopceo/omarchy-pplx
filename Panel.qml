import QtQuick
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
  property bool copyAvailable: false
  property bool hasSearched: false
  property bool isSearching: false
  property var hits: []
  property var history: []
  property string lastError: ""
  property int elapsedMs: 0
  property string currentTab: "ask" // "ask" | "history"
  // Search-option chip state — session-only (never persisted), allowlisted
  // values only; the helper re-validates before pplx ever sees them.
  property string recency: ""   // "" | "day" | "week" | "month"
  property string context: ""   // "" | "low" | "medium" | "high"
  // The draft lives on root, not in the editor: the Loader destroys the Ask
  // tab's item on every switch, and the draft is what a History row writes
  // into to stage a re-ask.
  property string draft: ""
  property real animPulse: 0.0

  readonly property bool ready: installed && authed

  // Palette — dayflow idiom: theme tokens plus derived alpha fills, no
  // hardcoded colors anywhere in the panel.
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property color urgent: Color.urgent
  readonly property color accent: Color.accent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string pluginRoot: {
    var p = Qt.resolvedUrl(".").toString()
    if (p.indexOf("file://") === 0) p = p.substring(7)
    if (p.length > 1 && p.charAt(p.length - 1) === "/") p = p.substring(0, p.length - 1)
    return p
  }

  readonly property string statusText: !statusKnown ? "CHECKING" : !installed ? "NOT INSTALLED" : !authed ? "NO KEY" : "READY"
  readonly property color statusColor: !statusKnown ? dim : !installed ? dim : !authed ? urgent : accent

  function _rgb(c) {
    if (typeof c === "string") {
      var h = c.charAt(0) === "#" ? c.substring(1) : c
      if (h.length === 8) h = h.substring(0, 6)
      if (h.length === 3)
        h = h.charAt(0) + h.charAt(0) + h.charAt(1) + h.charAt(1) + h.charAt(2) + h.charAt(2)
      if (h.length === 6)
        return [parseInt(h.substring(0, 2), 16) / 255,
                parseInt(h.substring(2, 4), 16) / 255,
                parseInt(h.substring(4, 6), 16) / 255]
      return [1, 1, 1]
    }
    if (c === undefined || c === null) return [1, 1, 1]
    return [c.r, c.g, c.b]
  }

  function fillFor(c, alpha) {
    var rgb = _rgb(c)
    return Qt.rgba(rgb[0], rgb[1], rgb[2], alpha)
  }
  function accentFill(alpha) {
    var c = (Color.accent === undefined || Color.accent === null) ? foreground : Color.accent
    return fillFor(c, alpha)
  }
  function fgFill(alpha) { return fillFor(foreground, alpha) }

  // "42s ago" / "3m ago" for history rows; "" on an unparseable stamp.
  function relTime(iso) {
    var t = new Date(String(iso || "")).getTime()
    if (isNaN(t)) return ""
    var s = Math.max(0, Math.floor((Date.now() - t) / 1000))
    if (s < 60) return s + "s ago"
    var m = Math.floor(s / 60)
    if (m < 60) return m + "m ago"
    var h = Math.floor(m / 60)
    if (h < 24) return h + "h ago"
    return Math.floor(h / 24) + "d ago"
  }

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
    from: 0.3; to: 1.0; duration: 1400; loops: Animation.Infinite
    running: root.opened; easing.type: Easing.InOutSine
  }

  // The quick-ask editor is inside the askTab component — reach it through
  // the Loader instead of by id.
  function askField() {
    var it = tabLoader.item
    return (it && it.askField) ? it.askField : null
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
    var q = draft.trim()
    if (q.length === 0 || searchProc.running) return
    hits = []; lastError = ""; elapsedMs = 0
    hasSearched = true; isSearching = true
    // The query is a single argv element behind `--` — no shell, no
    // interpolation. Chip state maps to flag pairs; the helper re-checks
    // each value against its allowlist and drops anything else.
    var cmd = [root.py, root.pluginRoot + "/bin/pplx_search.py"]
    if (root.recency !== "") cmd.push("--recency", root.recency)
    if (root.context !== "") cmd.push("--context", root.context)
    cmd.push("--", q)
    searchProc.command = cmd
    searchDeadline.restart()
    searchProc.running = true
  }

  function killSearch() { groupKill(searchProc); searchDeadline.stop(); isSearching = false }

  function openHit(url) {
    // xdg-open only gets a single argv element with an http(s) scheme.
    if (typeof url !== "string" || !/^https?:\/\//.test(url)) return
    Quickshell.execDetached(["/usr/bin/xdg-open", url])
  }

  function copyHit(url) {
    // wl-copy gets the URL as its sole argv element — the same http(s)
    // gate as openHit. Detached exec: nothing is read back.
    if (typeof url !== "string" || !/^https?:\/\//.test(url)) return
    Quickshell.execDetached(["/usr/bin/wl-copy", url])
  }

  // The delete verb rewrites history.json and re-emits the updated list —
  // the panel adopts it straight from the stdout payload.
  function deleteHistory(index) {
    if (deleteProc.running) return
    deleteProc.command = [root.py, root.pluginRoot + "/bin/pplx_status.py",
                          "--delete", String(index)]
    deleteDeadline.restart()
    deleteProc.running = true
  }

  // History row click: stage the query into the Ask editor — a re-ask is a
  // deliberate second Enter, never an implicit side effect.
  function reuseQuery(q) {
    draft = String(q || "")
    currentTab = "ask"
    Qt.callLater(function() { var f = askField(); if (f) f.forceActiveFocus() })
  }

  onOpenedChanged: {
    if (opened) { refreshStatus(); return }
    draft = ""
    var f = askField()
    if (f) f.text = ""
    killSearch()
  }

  // History rides along in the status payload — re-poll when the tab opens
  // so the list is never a poll interval stale.
  onCurrentTabChanged: if (currentTab === "history") refreshStatus()

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // Status probe: {"installed","authed","history"} — no network.
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
          root.copyAvailable = !!data.copy_available
          root.history = (Array.isArray(data.history) ? data.history : []).slice(0, 30)
          root.statusKnown = true
        } catch (e) {}
      }
    }
    onExited: statusDeadline.stop()
  }

  // Hard deadlines: a stuck helper is group-killed, never left running past
  // one poll interval.
  Timer { id: statusDeadline; interval: 8000; onTriggered: root.groupKill(statusProc) }
  Timer { id: statusTimer; interval: 30000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.refreshStatus() }

  // History delete: {"ok","history","error"} — spawned only by the row ✕.
  Process {
    id: deleteProc
    clearEnvironment: true
    environment: root.procEnv
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        deleteDeadline.stop()
        try {
          if (!text || text.trim().length === 0) { root.refreshStatus(); return }
          if (text.length > 300000) return
          var data = JSON.parse(text)
          if (Array.isArray(data.history))
            root.history = data.history.slice(0, 30)
          else
            root.refreshStatus()
        } catch (e) { root.refreshStatus() }
      }
    }
    onExited: deleteDeadline.stop()
  }

  Timer { id: deleteDeadline; interval: 8000; onTriggered: root.groupKill(deleteProc) }

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
            root.refreshStatus() // pull the journaled entry into History
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
    tooltipText: "Perplexity Search"
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
    focusTarget: { var f = root.askField(); return (root.currentTab === "ask" && f) ? f : keyCatcher }
    contentWidth: panel.fittedContentWidth(Style.space(500), 540)
    contentHeight: panel.fittedContentHeight(mainColumn.implicitHeight, 640)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      // While the query editor holds focus every key belongs to it —
      // Enter submits and Escape closes inside the TextInput itself.
      blocked: { var f = root.askField(); return !!f && f.activeFocus }
      onCloseRequested: root.close()
      onActivateRequested: if (root.currentTab === "ask" && root.draft.trim().length > 0) root.submitQuery()
      onTabRequested: function (direction) { root.switchPanel(direction) }

      Column {
        id: mainColumn
        width: parent.width
        spacing: Style.space(10)

        // ---- header ----
        Row {
          width: parent.width
          spacing: Style.space(10)

          Rectangle {
            id: iconTile
            width: Style.space(34); height: Style.space(34)
            radius: Style.cornerRadius
            color: root.accentFill(0.12)
            anchors.verticalCenter: parent.verticalCenter

            Text {
              anchors.centerIn: parent
              text: "󰍉"; textFormat: Text.PlainText
              color: root.accent
              font.family: root.fontFamily; font.pixelSize: Style.font.iconLarge
            }
          }

          Column {
            width: parent.width - iconTile.width - statusPill.width - parent.spacing * 2
            spacing: Style.space(2)
            anchors.verticalCenter: parent.verticalCenter

            Text {
              text: "Perplexity Search"; textFormat: Text.PlainText
              color: root.foreground
              font.family: root.fontFamily; font.pixelSize: Style.font.subtitle
              font.bold: true
            }
            Text {
              width: parent.width
              text: "quick-ask for the perplexity search api"; textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily; font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
          }

          Rectangle {
            id: statusPill
            height: Style.space(22)
            width: pillText.implicitWidth + Style.space(16)
            radius: height / 2
            color: root.fillFor(root.statusColor, 0.15)
            anchors.verticalCenter: parent.verticalCenter

            Text {
              id: pillText
              anchors.centerIn: parent
              text: root.statusText; textFormat: Text.PlainText
              color: root.statusColor
              font.family: root.fontFamily; font.pixelSize: Style.font.caption
              font.bold: true
              opacity: (root.isSearching || !root.statusKnown) ? root.animPulse : 1.0
            }
          }
        }

        // ---- setup pane: one bordered card, conditional copy ----
        Rectangle {
          visible: root.statusKnown && !root.ready
          width: parent.width
          height: stateColumn.implicitHeight + Style.space(24)
          radius: Style.cornerRadius
          color: root.fgFill(0.04)
          border.color: root.fgFill(0.10); border.width: 1

          Column {
            id: stateColumn
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: Style.space(12) }
            spacing: Style.space(4)

            Text {
              text: !root.installed ? "pplx CLI not found" : "No Perplexity API key"
              textFormat: Text.PlainText
              color: root.foreground
              font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall
              font.bold: true
            }
            Text {
              width: parent.width
              text: !root.installed
                  ? "Install pplx from github.com/perplexityai/perplexity-cli releases"
                  : "Set PERPLEXITY_API_KEY, or: omaseal set perplexity default"
              textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall
              wrapMode: Text.Wrap
            }
          }
        }

        // ---- tab bar ----
        Row {
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: ["ask", "history"]
            delegate: Rectangle {
              height: Style.space(28)
              width: tabLabel.implicitWidth + Style.space(16)
              radius: Style.cornerRadius
              color: root.currentTab === modelData ? root.accentFill(0.12)
                  : (tabMouse.containsMouse ? root.accentFill(0.06) : "transparent")
              border.color: root.currentTab === modelData ? root.accentFill(0.45) : "transparent"

              Text {
                id: tabLabel
                anchors.centerIn: parent
                text: modelData.charAt(0).toUpperCase() + modelData.slice(1)
                textFormat: Text.PlainText
                color: root.currentTab === modelData ? root.foreground : root.dim
                font.bold: root.currentTab === modelData
                font.family: root.fontFamily; font.pixelSize: Style.font.caption
              }

              MouseArea {
                id: tabMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.currentTab = modelData
              }
            }
          }
        }

        PanelSeparator { foreground: root.foreground }

        // ---- tab content ----
        Loader {
          id: tabLoader
          width: parent.width
          height: item ? item.implicitHeight : Style.space(60)
          sourceComponent: root.currentTab === "ask" ? askTab : historyTab
        }
      }
    }
  }

  // Shared option-chip: pill in the tab-pill idiom — accentFill selected,
  // fgFill unselected, hover lift. modelData carries {label, value, group}
  // where group names the root property ("recency"/"context") it toggles.
  Component {
    id: optionChip

    Rectangle {
      property bool sel: root[modelData.group] === modelData.value
      height: Style.space(22)
      width: chipLabel.implicitWidth + Style.space(14)
      radius: Style.cornerRadius
      color: sel ? root.accentFill(0.12)
          : (chipMouse.containsMouse ? root.fgFill(0.08) : root.fgFill(0.04))
      border.color: sel ? root.accentFill(0.45) : root.fgFill(0.10)
      border.width: 1

      Text {
        id: chipLabel
        anchors.centerIn: parent
        text: modelData.label; textFormat: Text.PlainText
        color: sel ? root.foreground : root.dim
        font.bold: sel
        font.family: root.fontFamily; font.pixelSize: Style.font.caption
      }

      MouseArea {
        id: chipMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        // Toggle: tapping the selected chip clears back to no flag.
        onClicked: root[modelData.group] =
            (root[modelData.group] === modelData.value ? "" : modelData.value)
      }
    }
  }

  // ---- Ask tab ----
  Component {
    id: askTab

    Column {
      property alias askField: queryField
      width: parent.width
      spacing: Style.space(10)
      Component.onCompleted: queryField.text = root.draft

      // Quick-ask row: single-line editor; Enter submits, Escape closes.
      // Every keystroke mirrors into root.draft so a tab switch (which
      // destroys this item) or a panel close (which clears the draft)
      // never strands half a query.
      Rectangle {
        visible: root.ready
        width: parent.width
        height: Style.space(36)
        radius: Style.cornerRadius
        color: root.fgFill(0.04)
        border.color: queryField.activeFocus ? root.accentFill(0.5) : root.fgFill(0.10)
        border.width: 1

        TextInput {
          id: queryField
          anchors { fill: parent; leftMargin: Style.space(12); rightMargin: Style.space(10) }
          verticalAlignment: TextInput.AlignVCenter
          clip: true
          color: root.foreground
          font.family: root.fontFamily; font.pixelSize: Style.font.body
          selectByMouse: true
          onAccepted: root.submitQuery()
          Keys.onEscapePressed: root.close()
          onTextChanged: root.draft = text

          Text {
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
            visible: queryField.text.length === 0
            text: "Ask anything…"; textFormat: Text.PlainText
            color: root.dim
            font: queryField.font
            elide: Text.ElideRight
          }
        }
      }

      // Search options: compact chip rows under the ask field. State is
      // session-only; submitQuery() maps it to the helper's allowlisted
      // flag pairs — nothing else can reach pplx.
      Column {
        visible: root.ready
        width: parent.width
        spacing: Style.space(6)

        Row {
          spacing: Style.space(6)

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Recency"; textFormat: Text.PlainText
            color: root.dim
            font.family: root.fontFamily; font.pixelSize: Style.font.caption
          }

          Repeater {
            model: [
              {"label": "Any", "value": "", "group": "recency"},
              {"label": "Day", "value": "day", "group": "recency"},
              {"label": "Week", "value": "week", "group": "recency"},
              {"label": "Month", "value": "month", "group": "recency"}
            ]
            delegate: optionChip
          }
        }

        Row {
          spacing: Style.space(6)

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Context"; textFormat: Text.PlainText
            color: root.dim
            font.family: root.fontFamily; font.pixelSize: Style.font.caption
          }

          Repeater {
            model: [
              {"label": "Low", "value": "low", "group": "context"},
              {"label": "Med", "value": "medium", "group": "context"},
              {"label": "High", "value": "high", "group": "context"}
            ]
            delegate: optionChip
          }
        }
      }

      // Indeterminate pulse while a search is in flight.
      Text {
        visible: root.isSearching
        text: "Searching…"; textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall
        opacity: root.animPulse
      }

      // Error banner.
      Text {
        visible: root.lastError !== "" && !root.isSearching
        width: parent.width
        text: "! " + root.lastError; textFormat: Text.PlainText
        color: root.urgent
        font.family: root.fontFamily; font.pixelSize: Style.font.body
        wrapMode: Text.WordWrap
      }

      // Count + latency line; doubles as the empty-result state.
      Text {
        visible: root.hasSearched && !root.isSearching && root.lastError === "" && root.ready
        width: parent.width
        text: root.hits.length > 0
            ? root.hits.length + " hits · " + root.elapsedMs + " ms" : "No results."
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily; font.pixelSize: Style.font.caption
      }

      // Result cards.
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
              height: hitColumn.implicitHeight + Style.space(16)
              radius: Style.cornerRadius
              color: root.fgFill(0.04)
              border.color: hitArea.containsMouse ? root.accentFill(0.4) : root.fgFill(0.08)
              border.width: 1

              Column {
                id: hitColumn
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: Style.space(8) }
                spacing: Style.space(4)

                // Domain chip left, date right.
                Item {
                  visible: modelData.domain !== "" || modelData.date !== ""
                  width: parent.width
                  height: Style.space(18)

                  Rectangle {
                    id: domainChip
                    visible: modelData.domain !== ""
                    anchors.left: parent.left
                    height: Style.space(18)
                    width: Math.max(Style.space(20),
                           Math.min(parent.width - Style.space(70),
                                    domainLabel.implicitWidth + Style.space(10)))
                    radius: Style.space(4)
                    color: root.fgFill(0.09)
                    clip: true

                    Text {
                      id: domainLabel
                      anchors.centerIn: parent
                      width: parent.width - Style.space(10)
                      text: modelData.domain; textFormat: Text.PlainText
                      color: root.dim
                      font.family: root.fontFamily; font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                  }

                  Text {
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter
                              rightMargin: root.copyAvailable ? Style.space(28) : 0 }
                    visible: modelData.date !== ""
                    text: modelData.date; textFormat: Text.PlainText
                    color: root.dim
                    font.family: root.fontFamily; font.pixelSize: Style.font.caption
                  }
                }

                Text {
                  width: parent.width
                  text: modelData.title; textFormat: Text.PlainText
                  color: root.foreground
                  font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall
                  font.bold: true
                  elide: Text.ElideRight
                }

                Text {
                  visible: modelData.snippet !== ""
                  width: parent.width
                  text: modelData.snippet; textFormat: Text.PlainText
                  color: root.dim
                  font.family: root.fontFamily; font.pixelSize: Style.font.caption
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

              // Copy URL — declared after hitArea so it stacks above the
              // card's click-through area; hidden unless wl-copy exists.
              Rectangle {
                visible: root.copyAvailable
                anchors { top: parent.top; topMargin: Style.space(8)
                          right: parent.right; rightMargin: Style.space(8) }
                width: Style.space(22); height: Style.space(22)
                radius: Style.cornerRadius
                color: copyMouse.containsMouse ? root.accentFill(0.15) : root.fgFill(0.06)
                border.color: copyMouse.containsMouse ? root.accentFill(0.45) : root.fgFill(0.10)
                border.width: 1

                Text {
                  anchors.centerIn: parent
                  text: "󰆏"; textFormat: Text.PlainText
                  color: copyMouse.containsMouse ? root.accent : root.dim
                  font.family: root.fontFamily; font.pixelSize: Style.font.body
                }

                MouseArea {
                  id: copyMouse
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.copyHit(modelData.url)
                }
              }
            }
          }
        }
      }

      // Brand footer — honest attribution, text mark only (no logo assets).
      Text {
        width: parent.width
        text: "Powered by the Perplexity Search API"
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily; font.pixelSize: Style.font.caption
        horizontalAlignment: Text.AlignHCenter
        opacity: 0.8
      }
    }
  }

  // ---- History tab ----
  Component {
    id: historyTab

    Column {
      width: parent.width
      spacing: Style.space(8)

      PanelSectionHeader {
        text: "RECENT QUERIES"
        foreground: root.foreground
        fontFamily: root.fontFamily
      }

      Text {
        visible: root.history.length === 0
        width: parent.width
        text: "No searches yet"; textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily; font.pixelSize: Style.font.caption
      }

      Flickable {
        visible: root.history.length > 0
        width: parent.width
        height: Math.min(Style.space(400), historyRows.implicitHeight)
        contentWidth: width
        contentHeight: historyRows.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: historyRows
          width: parent.width
          spacing: Style.space(2)

          Repeater {
            model: root.history
            delegate: Rectangle {
              width: historyRows.width
              height: histColumn.implicitHeight + Style.space(12)
              radius: Style.cornerRadius
              color: histMouse.containsMouse ? root.fgFill(0.05) : "transparent"

              Column {
                id: histColumn
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
                          leftMargin: Style.space(8); rightMargin: Style.space(28) }
                spacing: Style.space(2)

                Text {
                  width: parent.width
                  text: modelData.query || ""; textFormat: Text.PlainText
                  color: root.foreground
                  font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall
                  font.bold: true
                  elide: Text.ElideRight
                }
                Text {
                  width: parent.width
                  text: (modelData.hits_count || 0) + " hits · " + (modelData.elapsed_ms || 0) + "ms"
                      + (root.relTime(modelData.at) !== "" ? " · " + root.relTime(modelData.at) : "")
                  textFormat: Text.PlainText
                  color: root.dim
                  font.family: root.fontFamily; font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }

              MouseArea {
                id: histMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.reuseQuery(modelData.query)
              }

              // Delete this entry — declared after histMouse so it stacks
              // above the row's click-to-reuse area.
              Text {
                anchors { right: parent.right; rightMargin: Style.space(8)
                          verticalCenter: parent.verticalCenter }
                text: "✕"; textFormat: Text.PlainText
                color: delMouse.containsMouse ? root.urgent : root.dim
                font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall

                MouseArea {
                  id: delMouse
                  anchors.fill: parent
                  anchors.margins: -6
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.deleteHistory(index)
                }
              }
            }
          }
        }
      }
    }
  }
}
