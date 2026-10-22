import java.io.*;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

/** Local recovery-only invocation of retained trust import and verification. */
public class NativeCertifyTrustRecovery {
    public static void agentmain(String argument, Instrumentation instrumentation) throws Exception {
        Path folder=Path.of(argument).toRealPath();
        if (!folder.toString().startsWith("/opt/karnatakadbt/private/mosip-migration/remaining-three/original-certify-recovery-")) throw new SecurityException("Isolated retained recovery directory required");
        Class<?> application=null;
        for (Class<?> type:instrumentation.getAllLoadedClasses())
            if (type.getName().equals("org.springframework.boot.SpringApplication")) application=type;
        if(application==null) throw new IllegalStateException("Retained Spring runtime not found");
        ClassLoader loader=application.getClassLoader();Object hook=null;
        for(Field field:application.getDeclaredFields())
            if(Modifier.isStatic(field.getModifiers())&&field.getType().getName().endsWith("SpringApplicationShutdownHook")) {
                field.setAccessible(true);hook=field.get(null);
            }
        if(hook==null) throw new IllegalStateException("Retained contexts unavailable");
        Class<?> serviceType=Class.forName("io.mosip.kernel.partnercertservice.service.spi.PartnerCertificateManagerService",false,loader);
        Set<Object> beans=Collections.newSetFromMap(new IdentityHashMap<>());
        List<Object> contexts=new ArrayList<>();
        for(Field field:hook.getClass().getDeclaredFields()) {
            if(!Collection.class.isAssignableFrom(field.getType()))continue;
            field.setAccessible(true);
            for(Object context:new ArrayList<>((Collection<?>)field.get(hook))) {
                contexts.add(context);
                try { beans.addAll(((Map<?,?>)context.getClass().getMethod("getBeansOfType",Class.class).invoke(context,serviceType)).values()); }
                catch(NoSuchMethodException ignored) { }
            }
        }
        if(beans.size()!=1)throw new SecurityException("One retained trust manager required");
        Object service=beans.iterator().next();
        Class<?> request=Class.forName("io.mosip.kernel.partnercertservice.dto.CACertificateRequestDto",false,loader);
        Class<?> verifyRequest=Class.forName("io.mosip.kernel.partnercertservice.dto.CertificateTrustRequestDto",false,loader);
        Path input=folder.resolve("native-trust.bin");
        if(Files.size(input)>4*1024*1024)throw new SecurityException("Trust import size bound");
        List<String[]> rows=new ArrayList<>();
        try(DataInputStream in=new DataInputStream(Files.newInputStream(input))) {
            if(!in.readUTF().equals("KDBT-CERTIFY-TRUST-V2"))throw new SecurityException("Trust import version");
            int count=in.readInt();if(count<0||count>128)throw new SecurityException("Trust import count bound");
            for(int i=0;i<count;i++) {
                String domain=in.readUTF(),certificate=in.readUTF();
                if(!domain.matches("[A-Za-z0-9_.:-]{1,128}")||!certificate.startsWith("-----BEGIN CERTIFICATE-----"))throw new SecurityException("Trust import field mismatch");
                rows.add(new String[]{domain,certificate,Boolean.toString(in.readBoolean())});
            }
            if(in.read()!=-1)throw new SecurityException("Trailing trust input");
        }
        int imported=0;
        for(String[] row:rows) {
            Object value=request.getConstructor().newInstance();
            request.getMethod("setCertificateData",String.class).invoke(value,row[1]);
            request.getMethod("setPartnerDomain",String.class).invoke(value,row[0]);
            if(Boolean.parseBoolean(row[2]))serviceType.getMethod("uploadCACertificate",request).invoke(service,value);
            Object query=verifyRequest.getConstructor().newInstance();
            verifyRequest.getMethod("setCertificateData",String.class).invoke(query,row[1]);
            verifyRequest.getMethod("setPartnerDomain",String.class).invoke(query,row[0]);
            Object verified=serviceType.getMethod("verifyCertificateTrust",verifyRequest).invoke(service,query);
            if(!Boolean.TRUE.equals(verified.getClass().getMethod("getStatus").invoke(verified)))throw new SecurityException("Retained trust verification failed");
            verifyRequest.getMethod("setPartnerDomain",String.class).invoke(query,"KDBT_UNCONFIGURED_RECOVERY_DOMAIN");
            try {
                Object denied=serviceType.getMethod("verifyCertificateTrust",verifyRequest).invoke(service,query);
                if(Boolean.TRUE.equals(denied.getClass().getMethod("getStatus").invoke(denied)))throw new SecurityException("Cross-domain trust accepted");
            } catch(InvocationTargetException denied) {
                if(!denied.getCause().getClass().getName().equals("io.mosip.kernel.partnercertservice.exception.PartnerCertManagerException"))throw denied;
            }
            imported++;
        }
        int publicAliases=0;
        Path publicInput=folder.resolve("native-public-aliases.bin");
        if(Files.exists(publicInput)) {
            Class<?> keyType=Class.forName("io.mosip.kernel.keymanagerservice.service.KeymanagerService",false,loader);
            Set<Object> keyManagers=Collections.newSetFromMap(new IdentityHashMap<>());
            for(Object context:contexts) {
                try { keyManagers.addAll(((Map<?,?>)context.getClass().getMethod("getBeansOfType",Class.class).invoke(context,keyType)).values()); }
                catch(NoSuchMethodException ignored) { }
            }
            if(keyManagers.size()!=1)throw new SecurityException("One retained key manager required");
            try(DataInputStream in=new DataInputStream(Files.newInputStream(publicInput))) {
                if(!in.readUTF().equals("KDBT-PUBLIC-ALIASES-V1"))throw new SecurityException("Public alias version");
                int count=in.readInt();if(count<0||count>128)throw new SecurityException("Public alias bound");
                for(int i=0;i<count;i++) {
                    String applicationId=in.readUTF(),reference=in.readUTF(),expected=in.readUTF();
                    Object response=keyType.getMethod("getCertificate",String.class,Optional.class).invoke(keyManagers.iterator().next(),applicationId,Optional.of(reference));
                    String certificate=(String)response.getClass().getMethod("getCertificate").invoke(response);
                    java.security.cert.CertificateFactory factory=java.security.cert.CertificateFactory.getInstance("X.509");
                    byte[] actual=factory.generateCertificate(new ByteArrayInputStream(certificate.getBytes(java.nio.charset.StandardCharsets.US_ASCII))).getEncoded();
                    byte[] wanted=factory.generateCertificate(new ByteArrayInputStream(expected.getBytes(java.nio.charset.StandardCharsets.US_ASCII))).getEncoded();
                    if(!java.security.MessageDigest.isEqual(actual,wanted))throw new SecurityException("Retained public alias does not match native registration");
                    publicAliases++;
                }
                if(in.read()!=-1)throw new SecurityException("Trailing public alias data");
            }
        }
        Files.writeString(folder.resolve("native-trust-recovered.json"),"{\"native_ca_entries_verified_by_original_manager\":"+imported+",\"public_aliases_read_by_original_manager\":"+publicAliases+",\"unconfigured_domain_rejected\":true,\"local_recovery_only\":true}",StandardOpenOption.CREATE_NEW);
    }
}
