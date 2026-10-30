plugins { application }

dependencies {
    implementation(project(":lib:util"))
    implementation(projects.lib.httpClient)
    testImplementation(projects.missing)
}

application {
    mainClass.set("shop.AppKt")
}
