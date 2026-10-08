import Foundation

extension String {
    /// English UI copy, translated for the current language. The string is the catalog key.
    /// Text that is not in the catalog — layer names, paths, numbers — comes back unchanged,
    /// so stored document values can be shown without rewriting them.
    nonisolated var uiLocalized: String {
        Bundle.main.localizedString(forKey: self, value: self, table: "Localizable")
    }
}

/// Substitutes `args` into the localized form of an English format string.
/// The Chinese translation must keep the same specifiers, in the same order.
nonisolated func uiFormat(_ key: String, _ args: CVarArg...) -> String {
    String(format: key.uiLocalized, locale: .current, arguments: args)
}
