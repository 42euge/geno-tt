// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "GenoTTMenuBar",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "GenoTTMenuBar",
            targets: ["GenoTTMenuBar"]
        )
    ],
    targets: [
        .executableTarget(
            name: "GenoTTMenuBar",
            exclude: ["Resources/Info.plist"]
        )
    ]
)
