import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.*;
import java.security.cert.X509Certificate;
import java.security.interfaces.RSAPrivateKey;
import java.util.*;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;

/** Reference private keys stay inside JCA; only authenticated wrapped bytes leave. */
public class NativeReferenceKeyRecovery {
    static void field(Object target,String name,Object value) throws Exception {
        var field=target.getClass().getDeclaredField(name);field.setAccessible(true);field.set(target,value);
    }
    public static void main(String[] args) throws Exception {
        if(args.length!=1)throw new SecurityException("Private recovery directory required");
        Path folder=Path.of(args[0]).toRealPath();
        if(!folder.startsWith("/opt/karnatakadbt/private/mosip-migration/remaining-three")
            || !Files.getOwner(folder).getName().equals("root")
            || !Files.getPosixFilePermissions(folder).equals(PosixFilePermissions.fromString("rwx------")))
            throw new SecurityException("Protected recovery directory required");
        ObjectMapper mapper=new ObjectMapper();JsonNode request=mapper.readTree(folder.resolve("reference-wrap-request.json").toFile());
        char[] password=Files.readString(folder.resolve("p12-password")).toCharArray();
        KeyStore store=KeyStore.getInstance("PKCS12");
        try(var input=Files.newInputStream(folder.resolve("recovered.p12"))){store.load(input,password);}
        Security.addProvider(new org.bouncycastle.jce.provider.BouncyCastleProvider());
        Object crypto=Class.forName("io.mosip.kernel.crypto.jce.core.CryptoCore").getConstructor().newInstance();
        crypto.getClass().getMethod("init").invoke(crypto);
        field(crypto,"tagLength",request.path("tag_length").asInt());
        field(crypto,"symmetricAlgorithm",request.path("symmetric_algorithm").asText());
        field(crypto,"asymmetricAlgorithm",request.path("asymmetric_algorithm").asText());
        field(crypto,"keystoreType",request.path("keystore_type").asText());
        Object generator=Class.forName("io.mosip.kernel.keygenerator.bouncycastle.KeyGenerator").getConstructor().newInstance();
        field(generator,"symmetricKeyAlgorithm","AES");field(generator,"symmetricKeyLength",256);
        field(generator,"secureRandom",new SecureRandom());
        Object utility=Class.forName("io.mosip.kernel.keymanagerservice.util.KeymanagerUtil").getConstructor().newInstance();
        field(utility,"cryptoCore",crypto);field(utility,"keyGenerator",generator);
        field(utility,"keySplitter",request.path("splitter").asText());field(utility,"symmetricAlgorithmName","AES");
        ArrayNode result=mapper.createArrayNode();
        if(!request.path("references").isArray() || request.path("references").size()>4096)
            throw new SecurityException("Bounded reference inventory required");
        for(JsonNode row:request.path("references")) {
            String id=row.path("id").asText(),master=row.path("master").asText();
            if(id.equals(master)||!store.isKeyEntry(id)||!store.isKeyEntry(master))throw new SecurityException("Scoped private aliases required");
            PrivateKey key=(PrivateKey)store.getKey(id,password),parent=(PrivateKey)store.getKey(master,password);
            if(!(parent instanceof RSAPrivateKey))throw new SecurityException("RSA wrapping master required");
            field(crypto,"asymmetricKeyLength",((RSAPrivateKey)parent).getModulus().bitLength());
            var certificate=(X509Certificate)store.getCertificate(id);
            byte[] encrypted=(byte[])utility.getClass().getMethod("encryptKey",PrivateKey.class,PublicKey.class).invoke(utility,key,store.getCertificate(master).getPublicKey());
            byte[] recovered=(byte[])utility.getClass().getMethod("decryptKey",byte[].class,PrivateKey.class,PublicKey.class).invoke(utility,encrypted,parent,store.getCertificate(master).getPublicKey());
            if(!MessageDigest.isEqual(key.getEncoded(),recovered))throw new SecurityException("Original private-key unwrap differs");
            Arrays.fill(recovered,(byte)0);
            var record=result.addObject();record.put("id",id);record.put("master",master);
            record.put("private_key",(String)Class.forName("io.mosip.kernel.core.util.CryptoUtil").getMethod("encodeToURLSafeBase64",byte[].class).invoke(null,encrypted));
            record.put("certificate_sha256",HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded())));
        }
        Path output=folder.resolve("reference-wrapped-keys.json");
        Files.writeString(output,mapper.writeValueAsString(result),StandardOpenOption.CREATE_NEW);
        Files.setPosixFilePermissions(output,PosixFilePermissions.fromString("rw-------"));
        Arrays.fill(password,'\0');System.out.print(result.size());
    }
}
