# Windows Recovery Partition পুনরায় তৈরির ধাপসমূহ

> **তারিখ:** Tuesday, March 10, 2026  
> **কম্পিউটার:** WIN-21J0PDA3P4M  
> **OS:** Microsoft Windows 10.0.26100

---

## ধাপ ১: DiskPart চালু করা

```cmd
diskpart
```

> (DiskPart হলো Windows-এর একটি built-in disk management tool। এটি দিয়ে partition তৈরি, মোছা, ফরম্যাট ও কনফিগার করা যায়।)

**Output:**
```
Microsoft DiskPart version 10.0.26100.1150

Copyright (C) Microsoft Corporation.
On computer: WIN-21J0PDA3P4M
```

---

## ধাপ ২: সকল Disk দেখা

```cmd
DISKPART> list disk
```

> (কম্পিউটারে কতটি disk আছে এবং তাদের সাইজ ও স্ট্যাটাস দেখার জন্য এই কমান্ড ব্যবহার করা হয়েছে।)

**Output:**
```
  Disk ###  Status         Size     Free     Dyn  Gpt
  --------  -------------  -------  -------  ---  ---
  Disk 0    Online          110 GB  1024 KB        *
```

---

## ধাপ ৩: Disk 0 সিলেক্ট করা

```cmd
DISKPART> select disk 0
```

> (আমাদের কাজ করার জন্য Disk 0 বেছে নেওয়া হয়েছে, কারণ এটিই একমাত্র ও মূল system disk।)

**Output:**
```
Disk 0 is now the selected disk.
```

---

## ধাপ ৪: Disk 0-এর সকল Partition দেখা

```cmd
DISKPART> list part
```

> (Disk 0-এ কতটি partition আছে, তাদের ধরন, সাইজ ও অফসেট দেখার জন্য এই কমান্ড ব্যবহার করা হয়েছে।)

**Output:**
```
  Partition ###  Type              Size     Offset
  -------------  ----------------  -------  -------
  Partition 1    System             100 MB  1024 KB
  Partition 2    Reserved            16 MB   101 MB
  Partition 3    Primary            109 GB   117 MB
  Partition 4    Recovery           674 MB   109 GB
```

---

## ধাপ ৫: পুরনো Recovery Partition (Partition 4) সিলেক্ট করা

```cmd
DISKPART> select part 4
```

> (পুরনো ও ছোট আকারের Recovery Partition টি সিলেক্ট করা হয়েছে, কারণ এটি মাত্র ৬৭৪ MB যা নতুন WinRE রাখার জন্য যথেষ্ট নয়।)

**Output:**
```
Partition 4 is now the selected partition.
```

---

## ধাপ ৬: পুরনো Recovery Partition মুছে ফেলা

```cmd
DISKPART> delete part override
```

> (`override` ফ্ল্যাগ দিয়ে partition টি জোর করে মুছে ফেলা হয়েছে। সাধারণত Windows protected partition মুছতে দেয় না, তাই `override` লাগে।)

**Output:**
```
DiskPart successfully deleted the selected partition.
```

---

## ধাপ ৭: Partition মোছার পর লিস্ট চেক করা

```cmd
DISKPART> list part
```

> (নিশ্চিত করা হয়েছে যে Partition 4 সফলভাবে মুছে গেছে কিনা।)

**Output:**
```
  Partition ###  Type              Size     Offset
  -------------  ----------------  -------  -------
  Partition 1    System             100 MB  1024 KB
  Partition 2    Reserved            16 MB   101 MB
  Partition 3    Primary            109 GB   117 MB
```

---

## ধাপ ৮: Primary Partition (Partition 3) সিলেক্ট করা

```cmd
DISKPART> select part 3
```

> (মূল Windows partition টি সিলেক্ট করা হয়েছে, কারণ এর শেষ থেকে কিছু জায়গা কেটে নতুন Recovery Partition তৈরি করতে হবে।)

**Output:**
```
Partition 3 is now the selected partition.
```

---

## ধাপ ৯: Primary Partition থেকে ১০২৪ MB জায়গা সংকুচিত করা

```cmd
DISKPART> shrink desired=1024
```

> (Partition 3 থেকে ১০২৪ MB (১ GB) কেটে নেওয়া হয়েছে যাতে নতুন Recovery Partition তৈরির জন্য unallocated space পাওয়া যায়। নতুন WinRE image বড় হওয়ায় আগের ৬৭৪ MB যথেষ্ট ছিল না।)

**Output:**
```
DiskPart successfully shrunk the volume by: 1024 MB
```

---

## ধাপ ১০: নতুন Recovery Partition তৈরি করা

```cmd
DISKPART> create partition primary
```

> (এইমাত্র যে unallocated space তৈরি হয়েছে সেই জায়গায় একটি নতুন primary partition তৈরি করা হয়েছে, যেটিকে পরে Recovery Partition হিসেবে কনফিগার করা হবে।)

**Output:**
```
DiskPart succeeded in creating the specified partition.
```

---

## ধাপ ১১: নতুন Partition ফরম্যাট করা

```cmd
DISKPART> format quick fs=ntfs label="Recovery"
```

> (নতুন partition টিকে NTFS ফাইল সিস্টেমে দ্রুত ফরম্যাট করা হয়েছে এবং লেবেল দেওয়া হয়েছে "Recovery"। `quick` দিলে সম্পূর্ণ সেক্টর চেক না করে দ্রুত ফরম্যাট হয়।)

**Output:**
```
  100 percent completed

DiskPart successfully formatted the volume.
```

---

## ধাপ ১২: Partition-এ Recovery Partition ID সেট করা

```cmd
DISKPART> set id="de94bba4-06d1-4d40-a16a-bfd50179d6ac"
```

> (এই GUID টি হলো Windows Recovery Partition-এর official identifier। এটি সেট না করলে Windows এই partition টিকে সাধারণ data partition হিসেবে দেখবে, Recovery হিসেবে চিনবে না।)

**Output:**
```
DiskPart successfully set the partition ID.
```

---

## ধাপ ১৩: GPT Attributes সেট করা

```cmd
DISKPART> gpt attributes=0x8000000000000001
```

> (এই attribute দিয়ে partition টিকে "Required Partition" ও "No auto-assign drive letter" হিসেবে মার্ক করা হয়েছে। `0x8000000000000001` মানে হলো partition টি system-required এবং File Explorer-এ দেখাবে না।)

**Output:**
```
DiskPart successfully assigned the attributes to the selected GPT partition.
```

---

## ধাপ ১৪: Recovery Partition-এ Drive Letter R: অ্যাসাইন করা

```cmd
DISKPART> assign letter=R
```

> (পরবর্তী ধাপে WinRE ফাইল কপি করার জন্য সাময়িকভাবে R: লেটার দেওয়া হয়েছে। কাজ শেষে এটি সরিয়ে নেওয়া হবে।)

**Output:**
```
DiskPart successfully assigned the drive letter or mount point.
```

---

## ধাপ ১৫: DiskPart থেকে বের হওয়া

```cmd
DISKPART> exit
```

> (DiskPart-এর কাজ সম্পন্ন হওয়ায় এটি বন্ধ করা হয়েছে।)

**Output:**
```
Leaving DiskPart...
```

---

## ধাপ ১৬: Windows RE নিষ্ক্রিয় করা

```cmd
reagentc /disable
```

> (WinRE-র ফাইল ও কনফিগারেশন পরিবর্তন করার আগে এটিকে disable করতে হয়, নাহলে ফাইলগুলো locked থাকে।)

**Output:**
```
REAGENTC.EXE: Windows RE is already disabled.
```

> *(ইতোমধ্যে disabled ছিল, তাই এই বার্তা এসেছে।)*

---

## ধাপ ১৭: DISM Mount Directory তৈরি করা

```cmd
mkdir C:\DISM
```

> (Windows ISO/WIM image mount করার জন্য একটি খালি ফোল্ডার তৈরি করা হয়েছে। DISM mount করতে একটি empty directory লাগে।)

---

## ধাপ ১৮: Install.wim Image Mount করা

```cmd
DISM /Mount-image /imagefile:E:\sources\install.wim /Index:1 /MountDir:C:\DISM /readonly /optimize
```

> (E: drive-এ থাকা Windows installation media থেকে install.wim ফাইলের প্রথম ইনডেক্স (Index:1) C:\DISM ফোল্ডারে mount করা হয়েছে। `/readonly` দিয়ে শুধু পড়ার জন্য এবং `/optimize` দিয়ে দ্রুত mount করা হয়েছে। এতে fresh WinRE.wim ফাইলটি পাওয়া যাবে।)

**Output:**
```
Deployment Image Servicing and Management tool
Version: 10.0.26100.1150

Mounting image
[==========================100.0%==========================]
The operation completed successfully.
```

---

## ধাপ ১৯: Mounted Image থেকে Recovery ফাইল কপি করা

```cmd
robocopy /MIR /XJ C:\DISM\Windows\System32\Recovery\ C:\Windows\System32\Recovery
```

> (Mounted image-এর ভেতর থেকে fresh Recovery ফোল্ডারের সব কিছু (WinRE.wim ও ReAgent.xml) বর্তমান Windows-এর System32\Recovery ফোল্ডারে কপি করা হয়েছে। `/MIR` মানে mirror করা (destination-এ extra ফাইল থাকলে মুছবে), `/XJ` মানে Junction point skip করা।)

**Output:**
```
-------------------------------------------------------------------------------
   ROBOCOPY     ::     Robust File Copy for Windows
-------------------------------------------------------------------------------

  Started : Tuesday, March 10, 2026 8:15:54 PM
   Source : C:\DISM\Windows\System32\Recovery\
     Dest : C:\Windows\System32\Recovery\

    Files : *.*

  Options : *.* /S /E /DCOPY:DA /COPY:DAT /PURGE /MIR /XJ /R:1000000 /W:30

------------------------------------------------------------------------------

                           2    C:\DISM\Windows\System32\Recovery\
100%        Older                    837        ReAgent.xml
100%        New File             508.0 m        Winre.wim

------------------------------------------------------------------------------

               Total    Copied   Skipped  Mismatch    FAILED    Extras
    Dirs :         1         0         1         0         0         0
   Files :         2         2         0         0         0         0
   Bytes :  508.06 m  508.06 m         0         0         0         0
   Times :   0:00:02   0:00:02                       0:00:00   0:00:00


   Speed :           192,885,259 Bytes/sec.
   Speed :            11,036.983 MegaBytes/min.
   Ended : Tuesday, March 10, 2026 8:15:57 PM
```

---

## ধাপ ২০: Mounted Image Unmount করা

```cmd
DISM /Unmount-image /MountDir:C:\DISM /discard
```

> (কাজ শেষ হয়েছে, তাই C:\DISM থেকে image unmount করা হয়েছে। `/discard` মানে কোনো পরিবর্তন সেভ না করে unmount করা, কারণ image টি readonly ছিল।)

**Output:**
```
Deployment Image Servicing and Management tool
Version: 10.0.26100.1150

Unmounting image
[==========================100.0%==========================]
The operation completed successfully.
```

---

## ধাপ ২১: Recovery Partition-এ ফোল্ডার তৈরি করা

```cmd
mkdir R:\Recovery\WindowsRE
```

> (R: drive (নতুন Recovery Partition)-এ WinRE ফাইল রাখার জন্য প্রয়োজনীয় ফোল্ডার স্ট্রাকচার তৈরি করা হয়েছে। reagentc এই নির্দিষ্ট পাথেই WinRE.wim খোঁজে।)

---

## ধাপ ২২: WinRE.wim ফাইল Recovery Partition-এ কপি করা

```cmd
xcopy /h C:\Windows\System32\Recovery\Winre.wim R:\Recovery\WindowsRE\
```

> (System32\Recovery থেকে WinRE.wim ফাইলটি নতুন Recovery Partition-এ কপি করা হয়েছে। `/h` ফ্ল্যাগ দিয়ে hidden ফাইলও কপি করা যায়, কারণ Winre.wim সাধারণত hidden থাকে।)

**Output:**
```
C:\Windows\System32\Recovery\Winre.wim
1 File(s) copied
```

---

## ধাপ ২৩: নতুন Recovery Partition-এর Path Windows RE-তে সেট করা

```cmd
reagentc /setreimage /path R:\Recovery\WindowsRE /target C:\Windows
```

> (Windows-কে জানানো হয়েছে যে WinRE এখন নতুন partition-এ (R:\Recovery\WindowsRE) আছে। `/target C:\Windows` দিয়ে বলা হয়েছে কোন Windows installation-এর জন্য এটি কনফিগার করতে হবে।)

**Output:**
```
Directory set to: \\?\GLOBALROOT\device\harddisk0\partition4\Recovery\WindowsRE

REAGENTC.EXE: Operation Successful.
```

---

## ধাপ ২৪: Windows RE সক্রিয় করা

```cmd
reagentc /enable
```

> (সব কনফিগারেশন শেষ হওয়ার পর Windows Recovery Environment পুনরায় enable করা হয়েছে।)

**Output:**
```
REAGENTC.EXE: Operation Successful.
```

---

## ধাপ ২৫: Windows RE স্ট্যাটাস যাচাই করা (১ম বার)

```cmd
reagentc /info
```

> (Windows RE সঠিকভাবে enable হয়েছে কিনা এবং সঠিক location-এ আছে কিনা তা যাচাই করা হয়েছে।)

**Output:**
```
Windows Recovery Environment (Windows RE) and system reset configuration
Information:

    Windows RE status:         Enabled
    Windows RE location:       \\?\GLOBALROOT\device\harddisk0\partition4\Recovery\WindowsRE
    Boot Configuration Data (BCD) identifier: 49337674-1cd6-11f1-9c45-be1ac8ff0e7b
    Recovery image location:
    Recovery image index:      0
    Custom image location:
    Custom image index:        0

REAGENTC.EXE: Operation Successful.
```

---

## ধাপ ২৬: DiskPart পুনরায় চালু করে Final Partition লেআউট চেক করা

```cmd
diskpart
DISKPART> list disk
DISKPART> select disk 0
DISKPART> list part
```

> (সব কাজ শেষে চূড়ান্ত partition layout যাচাই করা হয়েছে। Partition 4 এখন ১৬৯৯ MB (প্রায় ১.৭ GB) যা আগের ৬৭৪ MB-এর চেয়ে অনেক বড়।)

**Output:**
```
  Disk ###  Status         Size     Free     Dyn  Gpt
  --------  -------------  -------  -------  ---  ---
  Disk 0    Online          110 GB      0 B        *

  Partition ###  Type              Size     Offset
  -------------  ----------------  -------  -------
  Partition 1    System             100 MB  1024 KB
  Partition 2    Reserved            16 MB   101 MB
  Partition 3    Primary            108 GB   117 MB
  Partition 4    Recovery          1699 MB   108 GB
```

---

## ধাপ ২৭: Recovery Partition থেকে Drive Letter সরিয়ে নেওয়া

```cmd
DISKPART> select part 4
DISKPART> remove letter=R
```

> (WinRE কপি করার সময় সাময়িকভাবে R: লেটার দেওয়া হয়েছিল। এখন কাজ শেষ হয়েছে, তাই R: লেটারটি সরিয়ে নেওয়া হয়েছে যাতে Recovery Partition File Explorer-এ না দেখায় এবং সুরক্ষিত থাকে।)

**Output:**
```
DiskPart successfully removed the drive letter or mount point.
```

---

## ধাপ ২৮: Final Status যাচাই করা

```cmd
reagentc /info
```

> (সব কিছু সম্পন্ন হওয়ার পর আরেকবার চূড়ান্ত যাচাই করা হয়েছে। Windows RE Enabled আছে এবং সঠিক নতুন partition (partition4)-এ রয়েছে।)

**Output:**
```
Windows Recovery Environment (Windows RE) and system reset configuration
Information:

    Windows RE status:         Enabled
    Windows RE location:       \\?\GLOBALROOT\device\harddisk0\partition4\Recovery\WindowsRE
    Boot Configuration Data (BCD) identifier: 49337674-1cd6-11f1-9c45-be1ac8ff0e7b
    Recovery image location:
    Recovery image index:      0
    Custom image location:
    Custom image index:        0

REAGENTC.EXE: Operation Successful.
```

---

## সারসংক্ষেপ

| ধাপ | কাজ |
|-----|-----|
| ১–৬ | পুরনো ছোট Recovery Partition (৬৭৪ MB) মুছে ফেলা |
| ৭–১৩ | Primary Partition থেকে ১ GB কেটে নতুন বড় Recovery Partition তৈরি ও কনফিগার করা |
| ১৪ | সাময়িকভাবে R: লেটার দেওয়া |
| ১৫–২০ | Windows ISO থেকে fresh WinRE.wim ফাইল বের করা |
| ২১–২৪ | নতুন Partition-এ WinRE সেটআপ ও Enable করা |
| ২৫–২৮ | সব কিছু যাচাই করা এবং Drive Letter সরিয়ে নেওয়া |

**চূড়ান্ত ফলাফল:** Windows Recovery Environment সফলভাবে একটি নতুন ও বড় Recovery Partition (১৬৯৯ MB) এ স্থানান্তরিত হয়েছে এবং সঠিকভাবে কার্যকর আছে।
