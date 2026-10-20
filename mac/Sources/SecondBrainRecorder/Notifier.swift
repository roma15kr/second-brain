import Foundation
import UserNotifications

/// Short notifications ("Dictation copied to the clipboard", "Recording stopped after 4 hours").
enum Notifier {
    static func show(_ text: String, title: String = "Second Brain Recorder") {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = text
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        }
    }
}
