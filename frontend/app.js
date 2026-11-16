let selectedFiles = [];
let outputDirectory = null;

const fileInput = document.getElementById("fileInput");
const folderInput = document.getElementById("folderInput");
const selectedFilesDiv = document.getElementById("selectedFiles");
const outputPath = document.getElementById("outputPath");
const convertBtn = document.getElementById("convertBtn");
const progressBar = document.getElementById("progressBar");
const statusText = document.getElementById("status");
const logs = document.getElementById("logs");

function addLog(message) {
    logs.textContent += "\n" + message;
    logs.scrollTop = logs.scrollHeight;
}

function displayFiles() {
    selectedFilesDiv.innerHTML = "";

    if (selectedFiles.length === 0) {
        selectedFilesDiv.textContent = "No files selected.";
        return;
    }

    selectedFiles.forEach(file => {
        const item = document.createElement("div");
        item.className = "file-item";
        item.textContent = file.webkitRelativePath || file.name;
        selectedFilesDiv.appendChild(item);
    });

    addLog(`${selectedFiles.length} SAS file(s) selected.`);
}

function acceptFiles(fileList) {
    const files = Array.from(fileList);
    const invalidFiles = files.filter(
        file => !file.name.toLowerCase().endsWith(".sas")
    );

    if (invalidFiles.length > 0) {
        alert("Please select only .sas files.");
        return;
    }

    selectedFiles = files;
    displayFiles();
}

document.getElementById("selectFilesBtn").onclick = () => {
    fileInput.click();
};

document.getElementById("selectFolderBtn").onclick = () => {
    folderInput.click();
};

fileInput.addEventListener("change", event => {
    acceptFiles(event.target.files);
    event.target.value = "";
});

folderInput.addEventListener("change", event => {
    acceptFiles(event.target.files);
    event.target.value = "";
});

document.getElementById("selectOutputBtn").onclick = async () => {
    try {
        if (!window.showDirectoryPicker) {
            alert("Your browser does not support folder selection. Please use Microsoft Edge.");
            return;
        }

        outputDirectory = await window.showDirectoryPicker({
            mode: "readwrite"
        });

        outputPath.textContent = outputDirectory.name;
        addLog("Output folder selected: " + outputDirectory.name);

    } catch (error) {
        if (error.name !== "AbortError") {
            addLog("Output folder selection failed: " + error.message);
        }
    }
};

async function saveZipContents(zipBlob) {
    const zip = await JSZip.loadAsync(zipBlob);

    const entries = Object.entries(zip.files).filter(
        ([name, entry]) => !entry.dir
    );

    let saved = 0;

    for (const [name, entry] of entries) {
        const parts = name.replace(/\\/g, "/").split("/");

        // Reject unsafe paths.
        if (parts.some(part => part === ".." || part === "")) {
            continue;
        }

        let currentDirectory = outputDirectory;

        for (const folderName of parts.slice(0, -1)) {
            currentDirectory = await currentDirectory.getDirectoryHandle(
                folderName,
                { create: true }
            );
        }

        const fileName = parts[parts.length - 1];

        const fileHandle = await currentDirectory.getFileHandle(
            fileName,
            { create: true }
        );

        const writable = await fileHandle.createWritable();
        await writable.write(await entry.async("blob"));
        await writable.close();

        saved++;

        progressBar.style.width =
            (85 + (saved / entries.length) * 15) + "%";
    }

    return saved;
}

convertBtn.addEventListener("click", async () => {

    if (selectedFiles.length === 0) {
        alert("Please select at least one SAS file or folder.");
        return;
    }

    if (!outputDirectory) {
        alert("Please select an output folder.");
        return;
    }

    convertBtn.disabled = true;
    progressBar.style.width = "5%";
    statusText.textContent = "Uploading SAS files...";
    logs.textContent = "Starting conversion...";

    try {
        const formData = new FormData();

        selectedFiles.forEach(file => {
            formData.append(
                "files",
                file,
                file.webkitRelativePath || file.name
            );
        });

        statusText.textContent = "Converting SAS programs...";
        progressBar.style.width = "10%";
        addLog("Sending files to FastAPI...");

        const response = await fetch("/convert-multiple", {
            method: "POST",
            body: formData
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || "Conversion failed.");
        }

        progressBar.style.width = "85%";
        statusText.textContent = "Saving generated Java files...";

        const zipBlob = await response.blob();
        const savedCount = await saveZipContents(zipBlob);

        progressBar.style.width = "100%";
        statusText.textContent =
            `Completed. ${savedCount} file(s) saved.`;

        addLog(`${savedCount} ZIP entries saved to output folder.`);
        addLog("Conversion completed successfully.");

    } catch (error) {
        statusText.textContent = "Conversion failed.";
        addLog("ERROR: " + error.message);
        alert(error.message);

    } finally {
        convertBtn.disabled = false;
    }
});