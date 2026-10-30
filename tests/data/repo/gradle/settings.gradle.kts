rootProject.name = "shop"

include(
    ":app",
    ":lib:util",
)
include(":lib:http-client")
includeBuild("plugins")
