# runtime yapılandırma şablonu

`config/runtime.example.json`, Golden iş akışı için isteğe bağlı çalışma yapılandırma şablonudur. Herhangi bir konuma kopyalayıp gerektiği gibi değiştirin,
ve `--runtime-config <path>` ile test senaryosu betiğine iletin.

```bash
python tests/solidworks_golden_workflow.py \
  --case parallel_gripper_retention_travel \
  --output output/verify \
  --runs 1 \
  --runtime-config config/runtime.example.json
```

## Alan beyaz listesi

Yapılandırma yalnızca aşağıdaki alanlara izin verir. **Bilinmeyen her alan reddedilir** (`BLOCKED: runtime-config bilinmeyen veya yasak alan içeriyor`),
bu bilinçli bir tercihtir: bu dosya SolidWorks sürümünü değiştirmek, geometrik toleransları ayarlamak veya incelemeyi atlamak için kullanılamaz.

| Alan | Tür | Varsayılan | Açıklama |
| --- | --- | --- | --- |
| `part_template` | string \| null | `null` | Parça şablonu `.prtdot`; `null`, SolidWorks kullanıcı tercihlerinden otomatik algılanacağı anlamına gelir |
| `assembly_template` | string \| null | `null` | Montaj şablonu `.asmdot`; **yalnızca montaj türü senaryolar (`native_extension=SLDASM`) bu alanı kabul eder** |
| `material_database` | string \| null | `null` | Malzeme kitaplığı `.sldmat`; `null`, kurulum dizininden otomatik algılanacağı anlamına gelir |
| `connect_timeout_seconds` | int | `60` | SolidWorks bağlantı zaman aşımı, `5..120` aralığına izin verilir |
| `cleanup_timeout_seconds` | int | `30` | Kapatma ve temizleme zaman aşımı, `5..60` aralığına izin verilir |

## Yol çözümleme kuralları

- **Göreli yollar**, projeyle birlikte taşınabilmesi için **yapılandırma dosyasının bulunduğu dizin** temel alınarak çözümlenir;
- **Mutlak yollar** olduğu gibi kullanılır;
- `null` olmayan şablon ve malzeme kitaplığı yolları **gerçekten var olan dosyalar** olmalı ve uzantıları eşleşmelidir, aksi halde derhal `BLOCKED` olur,
  sessizce geri dönüş yapılmaz.

Bu nedenle bu şablon varsayılan olarak tamamen `null` yazar — yani "tümünü otomatik algıla" — bu, SolidWorks'ün doğru kurulu olduğu her makinede çalışmalıdır.
Yalnızca otomatik algılama başarısız olduğunda belirli bir yol girilmesi gerekir.

## Doldurma örneği (lütfen gerçek yollarınızla değiştirin)

```jsonc
{
  "part_template": "relative/to/this/file/templates/gb_part.prtdot",
  "assembly_template": "C:\\ProgramData\\SolidWorks\\SOLIDWORKS 2026\\templates\\gb_assembly.asmdot",
  "material_database": "C:\\ProgramData\\SolidWorks\\SOLIDWORKS 2026\\lang\\chinese-simplified\\sldmaterials\\solidworks materials.sldmat",
  "connect_timeout_seconds": 90,
  "cleanup_timeout_seconds": 30
}
```

> Şablondaki SolidWorks sürüm numarası dizini (örneğin `SOLIDWORKS 2026`) kurulumdan kuruluma değişir, doğrudan kopyalamayın.
> Bu depoda daha önce kullanılan yerel yapılandırma geliştiriciye özel sürücü harfleri içeriyordu, **hiçbir** biçimde genel örneklere yazılmayacaktır.

## Otomatik algılamanın yedek mantığı

| Öğe | Yedek sırası |
| --- | --- |
| Şablon | Yapılandırma değeri → SolidWorks kullanıcı tercihlerindeki varsayılan şablon |
| Malzeme kitaplığı | Yapılandırma değeri → kurulum dizini altındaki `lang/english/sldmaterials` → `lang/chinese-simplified/sldmaterials` |
| Tür kitaplığı | Bkz. `docs/architecture/` ve `scripts/sw_capability_probe.py`: kayıt defteri/kısayol keşfi → `SOLIDWORKS_TYPELIB_DIRS` → genel kurulum yolları |

## Ortam değişkenleri

| Değişken | Kullanım |
| --- | --- |
| `SOLIDWORKS_TYPELIB_DIRS` | Standart olmayan kurulum konumlarında, tür kitaplığı ve şablonların bulunduğu dizini açıkça belirtir (`os.pathsep` ile ayrılır) |
| `CADSTUDIO_SOLVER_DIRS` | CalculiX çözücü kök dizinini açıkça belirtir (`os.pathsep` ile ayrılır) |

Bu iki değişken yalnızca **keşif sırasını** etkiler; herhangi bir geometriyi, toleransı veya kabul ölçütünü değiştirmez.
